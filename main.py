"""
github-hunter (无 BigQuery 版 + 增量缓存 + 长期保留)
数据源: https://data.gharchive.org/<YYYY-MM-DD-H>.json.gz
"""
from __future__ import annotations
import os, io, gzip, json, time, shutil
import requests
import pandas as pd
from collections import Counter
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

from workspace import ensure_workspace, check_env_or_die
from github_api import fetch_repo_details_parallel, call_llm

PATHS = ensure_workspace(verbose=True)
check_env_or_die(("GH_TOKEN",))

# ── 路径与参数 ───────────────────────────────────────────────
CACHE_DIR    = PATHS["CACHE_DIR"]
RESULT_DIR   = PATHS["RESULT_DIR"]
WEB_OUT_DIR  = PATHS["WEB_OUT_DIR"]
HOURS_WINDOW = 24
KEEP_DAYS    = 365
FINAL_LAG_H  = 2
TOP_N_REPOS  = 1000
TOP_N_AI     = 50


# ── GH Archive 增量缓存 ──────────────────────────────────────
def _cache_path(ts: datetime):
    return CACHE_DIR / f"{ts.strftime('%Y-%m-%d')}-{ts.hour}.parquet"

def _is_hour_finalized(ts: datetime) -> bool:
    return (datetime.now(timezone.utc) - ts) >= timedelta(hours=FINAL_LAG_H)

def _download_and_count(ts: datetime):
    url = f"https://data.gharchive.org/{ts.strftime('%Y-%m-%d')}-{ts.hour}.json.gz"
    try:
        r = requests.get(url, timeout=120)
    except requests.RequestException as e:
        print(f"[NET] {url}: {e}"); return None
    if r.status_code == 404: return None
    if r.status_code != 200:
        print(f"[SKIP {r.status_code}] {url}"); return None

    counter: Counter = Counter()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(r.content)) as gz:
            for line in gz:
                try: ev = json.loads(line)
                except Exception: continue
                if ev.get("type") == "WatchEvent":
                    name = ev.get("repo", {}).get("name")
                    if name: counter[name] += 1
    except OSError as e:
        print(f"[GZIP] {url}: {e}"); return None
    return counter

def _load_or_fetch(ts: datetime) -> Counter:
    path = _cache_path(ts)
    if path.exists():
        df = pd.read_parquet(path)
        return Counter(dict(zip(df["repo_name"], df["count"])))
    counter = _download_and_count(ts)
    if counter is None:
        return Counter()
    if _is_hour_finalized(ts) and counter:
        pd.DataFrame(counter.items(), columns=["repo_name", "count"])\
          .to_parquet(path, compression="zstd", index=False)
    return counter

def prune_cache(keep_days: int = KEEP_DAYS):
    now = datetime.now(timezone.utc); removed = 0
    for p in CACHE_DIR.glob("*.parquet"):
        try:
            ts = datetime.strptime(p.stem, "%Y-%m-%d-%H").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if (now - ts) > timedelta(days=keep_days):
            p.unlink(); removed += 1
    if removed:
        print(f"[cache] pruned {removed} files older than {keep_days}d")

def collect_watch_events(hours_back: int = HOURS_WINDOW,
                         max_workers: int = 8) -> pd.DataFrame:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    hours = [now - timedelta(hours=i) for i in range(1, hours_back + 1)]
    cached, to_fetch = [], []
    for h in hours:
        (cached if _cache_path(h).exists() else to_fetch).append(h)
    print(f"[cache] window={hours_back}h hit={len(cached)} miss={len(to_fetch)}")

    total: Counter = Counter()
    for h in cached:
        total.update(_load_or_fetch(h))
    if to_fetch:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_load_or_fetch, h): h for h in to_fetch}
            for fut in tqdm(as_completed(futures), total=len(futures),
                            desc="GH Archive (miss)"):
                total.update(fut.result())
    return pd.DataFrame(total.most_common(TOP_N_REPOS),
                        columns=["repo_name", "star_count"])


# ── AI 总结(可选,统一走 github_api.call_llm) ───────────────
def _summarize_one(repo_name, star_count, created_at, current_stars):
    prompt = f"""请分析以下 GitHub 项目,用简洁的中文总结(100字以内):
项目名称: {repo_name}
最近新增星标: {star_count}
当前总星标: {current_stars}
创建时间: {created_at}

请回答:
1. 这个项目是做什么的?(推测)
2. 为什么值得关注?
输出格式: 直接输出总结内容, 不要标题。"""
    content, _ = call_llm([
        {"role": "system",
         "content": "你是一个技术分析师,擅长分析 GitHub 项目。"},
        {"role": "user", "content": prompt},
    ])
    return content



def generate_summaries(df: pd.DataFrame, top_n: int = TOP_N_AI) -> pd.DataFrame:
    df["ai_summary"] = None
    def _one(idx):
        row = df.iloc[idx]
        if pd.isna(row["created_at"]) or row["current_star_count"] is None:
            return idx, None
        return idx, _summarize_one(
            row["repo_name"], row["star_count"],
            row["created_at"], row["current_star_count"])
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_one, i): i for i in range(min(top_n, len(df)))}
        for fut in tqdm(as_completed(futures), total=len(futures), desc="AI summaries"):
            idx, summary = fut.result()
            df.at[df.index[idx], "ai_summary"] = summary
    return df


# ── 主流程 ───────────────────────────────────────────────────
def main():
    t0 = time.time()

    print(">> 1/3 GH Archive ingest ...")
    df = collect_watch_events(HOURS_WINDOW)
    prune_cache(KEEP_DAYS)
    if df.empty:
        print("[WARN] empty result"); return

    print(">> 2/3 GraphQL ...")
    df = fetch_repo_details_parallel(df)

    if os.environ.get("OPENROUTER_API_KEY"):
        print(f">> 3/3 AI summaries (top {TOP_N_AI}) ...")
        df = generate_summaries(df, TOP_N_AI)
    else:
        print(">> skip AI (OPENROUTER_API_KEY not set)")

    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
    df = df.sort_values("created_at", ascending=False)

    today = datetime.now().strftime("%Y-%m-%d")
    out = RESULT_DIR / f"result_{today}.csv"
    df.to_csv(out, index=False)
    shutil.copy(out, WEB_OUT_DIR / "result.csv")
    print(f"[done] {out}  rows={len(df)}  elapsed={time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
