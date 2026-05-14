"""
github-hunter 工作目录引导
首次 import 时自动创建所需子目录、.env 模板、.gitignore。
"""
from __future__ import annotations
import os
from pathlib import Path

ROOT        = Path(os.environ.get("HUNTER_HOME", Path.cwd())).resolve()
CACHE_DIR   = ROOT / ".cache"
RESULT_DIR  = ROOT / "result"
REPORT_DIR  = ROOT / "reports"
WEB_OUT_DIR = ROOT / "web" / "public" / "results"
ENV_PATH    = ROOT / ".env"
GITIGNORE   = ROOT / ".gitignore"

_SUBDIRS = (CACHE_DIR, RESULT_DIR, REPORT_DIR, WEB_OUT_DIR)

ENV_TEMPLATE = """\
# === GitHub Hunter 配置 ===
# 必填:GitHub Personal Access Token (public_repo 只读即可)
GH_TOKEN=

# 可选:OpenRouter Key,用于 AI 总结。留空则跳过该步骤。
OPENROUTER_API_KEY=
# 可选:首选模型 slug(:free 后缀的会随时间下线,失败会自动降级)
OPENROUTER_MODEL=deepseek/deepseek-chat-v3.1:free

# 可选:每日报告推送 webhook
# REPORT_WEBHOOK_URL=
# REPORT_WEBHOOK_STYLE=wecom    # wecom | tg | raw
"""

GITIGNORE_TEMPLATE = """\
.env
.cache/
result/
reports/
web/public/results/
__pycache__/
*.pyc
"""


def ensure_workspace(verbose: bool = True) -> dict:
    """幂等创建目录与默认文件,返回所有关键路径。"""
    created = []
    for d in _SUBDIRS:
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(d)

    if not ENV_PATH.exists():
        ENV_PATH.write_text(ENV_TEMPLATE, encoding="utf-8")
        created.append(ENV_PATH)

    if not GITIGNORE.exists():
        GITIGNORE.write_text(GITIGNORE_TEMPLATE, encoding="utf-8")
        created.append(GITIGNORE)

    if verbose and created:
        print(f"[workspace] root: {ROOT}")
        for p in created:
            tag = "FILE" if p.is_file() else "DIR "
            print(f"[workspace] +{tag}  {p.relative_to(ROOT)}")
        if ENV_PATH in created:
            print("[workspace] 已生成 .env 模板,请填入 GH_TOKEN 后再次运行。")

    return {
        "ROOT":        ROOT,
        "CACHE_DIR":   CACHE_DIR,
        "RESULT_DIR":  RESULT_DIR,
        "REPORT_DIR":  REPORT_DIR,
        "WEB_OUT_DIR": WEB_OUT_DIR,
        "ENV_PATH":    ENV_PATH,
    }


def check_env_or_die(require_keys: tuple[str, ...] = ("GH_TOKEN",)) -> None:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=ENV_PATH)
    missing = [k for k in require_keys if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"""[fatal] 缺少环境变量:{', '.join(missing)}
        请在 {ENV_PATH} 中填写后重试。""")



if os.environ.get("HUNTER_AUTO_BOOTSTRAP", "1") == "1":
    ensure_workspace(verbose=False)
