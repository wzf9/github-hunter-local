"""
每日定时任务:
  - 在 .cache/ 上跑四种分析,写到 reports/
  - 可选:用 OpenRouter 生成一段 Markdown 总览(多模型自动降级)
  - 可选:推送到 Webhook (企业微信 / Telegram / 通用)
"""
from __future__ import annotations
import os, requests
from datetime import datetime, timedelta, timezone
import pandas as pd

from workspace import ensure_workspace, check_env_or_die
from github_api import call_llm

PATHS = ensure_workspace(verbose=False)
check_env_or_die(("GH_TOKEN",))
REPORT_DIR = PATHS["REPORT_DIR"]

from analyze import (
    fast_growing, acceleration_board, ghost_repo_candidates,
    top_n_on_day,
)


def _utc_date(offset_days: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=offset_days))\
           .strftime("%Y-%m-%d")


def collect() -> dict[str, pd.DataFrame]:
    today = _utc_date(0)
    yday  = _utc_date(-1)

    data = {
        "yesterday_top": top_n_on_day(yday, n=50),
        "acceleration":  acceleration_board(min_today=20, top_n=50),
        "fast_growing":  fast_growing(streak_days=3, daily_threshold=50,
                                      lookback_days=14),
        "ghosts":        ghost_repo_candidates(lookback_days=7, min_stars=30),
    }
    for name, df in data.items():
        path = REPORT_DIR / f"{name}_{today}.csv"
        df.to_csv(path, index=False)
        print(f"[report] {path}  rows={len(df)}")
    return data


def render_markdown(data: dict[str, pd.DataFrame]) -> str:
    today = _utc_date(0)

    def _fmt(df: pd.DataFrame, limit: int = 10) -> str:
        if df.empty:
            return "_(无数据)_\n"
        return df.head(limit).to_markdown(index=False) + "\n"

    sections = [
        f"# GitHub Hunter 日报 · {today}\n",
        "## 1. 昨日 Top 50(摘前 10)\n"        + _fmt(data["yesterday_top"]),
        "## 2. 今日加速度榜(摘前 10)\n"       + _fmt(data["acceleration"]),
        "## 3. 连续 3 天高速增长(摘前 10)\n" + _fmt(data["fast_growing"]),
        "## 4. 幽灵仓库候选(摘前 10)\n"       + _fmt(data["ghosts"]),
    ]
    md_body = "\n".join(sections)

    if not os.environ.get("OPENROUTER_API_KEY"):
        return md_body

    user_prompt = f"""你是一名 GitHub 趋势分析师。基于以下四张表,
用中文写一段 200 字以内的总览开篇(不要罗列表格),
突出今天最值得关注的 2~3 个项目,以及任何异常信号。

{md_body}"""

    intro, used_model = call_llm([
        {"role": "system", "content": "你擅长用简洁中文写技术趋势日报。"},
        {"role": "user",   "content": user_prompt},
    ])
    if not intro:
        return md_body

    print(f"[LLM] used model: {used_model}")
    return (
        f"# GitHub Hunter 日报 · {today}\n\n"
        f"> {intro}\n\n"
        + "\n".join(sections[1:])
    )



def push_webhook(markdown: str) -> None:
    url = os.environ.get("REPORT_WEBHOOK_URL")
    if not url:
        return
    style = os.environ.get("REPORT_WEBHOOK_STYLE", "raw")
    try:
        if style == "wecom":
            payload = {"msgtype": "markdown",
                       "markdown": {"content": markdown[:4000]}}
        elif style == "tg":
            payload = {"text": markdown[:4000], "parse_mode": "Markdown"}
        else:
            payload = {"text": markdown}
        r = requests.post(url, json=payload, timeout=30)
        print(f"[push] {style} -> {r.status_code}")
    except Exception as e:
        print(f"[push] {e}")


def main():
    data = collect()
    md   = render_markdown(data)
    path = REPORT_DIR / f"daily_{_utc_date(0)}.md"
    path.write_text(md, encoding="utf-8")
    print(f"[report] {path}")
    push_webhook(md)


if __name__ == "__main__":
    main()
