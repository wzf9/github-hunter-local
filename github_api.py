"""
GitHub GraphQL & OpenRouter LLM 统一封装
- fetch_repo_details / fetch_repo_details_parallel: 补 createdAt / stargazerCount
- call_llm: 多模型自动降级,环境变量 OPENROUTER_MODEL 优先
"""
from __future__ import annotations
import os
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm


# ── GitHub GraphQL ────────────────────────────────────────────
GRAPHQL_URL = "https://api.github.com/graphql"

GRAPHQL_QUERY_TEMPLATE = """
query 
}}
"""


def _headers() -> dict:
    """每次调用都重新读 env,避免 import 顺序问题"""
    token = os.environ.get("GH_TOKEN", "")
    return {
        "Authorization": f"bearer {token}",
        "Content-Type":  "application/json",
    }


def fetch_repo_details(repo_name: str):
    if "/" not in repo_name:
        return None, None
    owner, name = repo_name.split("/", 1)
    q = GRAPHQL_QUERY_TEMPLATE.format(repo_owner=owner, repo_name=name)
    try:
        r = requests.post(GRAPHQL_URL, json={"query": q},
                          headers=_headers(), timeout=30)
        if r.status_code == 200:
            repo = r.json().get("data", {}).get("repository")
            if repo:
                return repo.get("createdAt"), repo.get("stargazerCount")
        else:
            print(f"[GraphQL {r.status_code}] {repo_name}: {r.text[:120]}")
    except requests.RequestException as e:
        print(f"[GraphQL ERR] {repo_name}: {e}")
    return None, None


def fetch_repo_details_parallel(df: pd.DataFrame,
                                max_workers: int = 10) -> pd.DataFrame:
    df["created_at"]         = None
    df["current_star_count"] = None
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fetch_repo_details, row["repo_name"]): idx
                   for idx, row in df.iterrows()}
        for fut in tqdm(as_completed(futures), total=len(futures),
                        desc="Repo details"):
            idx = futures[fut]
            created_at, stars = fut.result()
            df.at[idx, "created_at"]         = created_at
            df.at[idx, "current_star_count"] = stars
    return df


# ── OpenRouter LLM (多模型自动降级) ──────────────────────────
DEFAULT_FALLBACK = [
    "deepseek/deepseek-chat-v3.1:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-30b-a3b:free",
    "google/gemma-3-27b-it:free",
    "xiaomi/mimo-v2-flash",          # 付费兜底
]
_DOWNGRADE_HINTS = ("404", "402", "429", "no longer available",
                    "free period has ended", "not available")


def _model_chain() -> list[str]:
    chain = []
    preferred = os.environ.get("OPENROUTER_MODEL")
    if preferred:
        chain.append(preferred)
    for m in DEFAULT_FALLBACK:
        if m not in chain:
            chain.append(m)
    return chain


def call_llm(messages: list[dict],
             temperature: float | None = None) -> tuple[str | None, str | None]:
    """返回 (content, used_model);若所有模型失败返回 (None, None)。"""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return None, None

    from openai import OpenAI
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

    last_err = None
    for model in _model_chain():
        try:
            kwargs = {"model": model, "messages": messages}
            if temperature is not None:
                kwargs["temperature"] = temperature
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content.strip(), model
        except Exception as e:
            msg = str(e).lower()
            last_err = e
            if any(h in msg for h in _DOWNGRADE_HINTS):
                print(f"[LLM] {model} 不可用,降级: {str(e)[:160]}")
                continue
            # 其它错误也试下一个模型
            print(f"[LLM] {model} 调用失败,继续降级: {str(e)[:160]}")
    print(f"[LLM] 所有模型均失败: {last_err}")
    return None, None
