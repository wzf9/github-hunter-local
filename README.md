# 🚀 GitHub Hunter · 本地化版
> **在线仪表盘**：[https://wzf9.github.io/github-hunter-local](https://wzf9.github.io/github-hunter-local)  
> 实时查看最近24小时热点榜单、加速榜、黑马候选等分析结果。
> **在项目爆火前的 24 小时,通过 GitHub 全量事件流捕捉潜在大黑马。**
> 不依赖 BigQuery、不依赖 GCP,纯本地 parquet 倒排索引 + DuckDB SQL。

本项目改造自 [chmod777john/github-hunter](https://github.com/chmod777john/github-hunter)。原版用 Google BigQuery 跑 `githubarchive.day.*` 表来统计最近 24 小时的 `WatchEvent`,需要 GCP 账号、SDK 与潜在查询费用。本仓库把数据源换成 [GH Archive](https://www.gharchive.org) 的原始 hourly `.json.gz`,加上**小时级增量缓存**与 **DuckDB 离线 SQL 分析**,把整套流程压成一个零依赖外部云服务的本地工具链。

---

## ✨ 与原版的关键差异

| 维度 | 原版 (BigQuery) | 本仓库 (GH Archive + DuckDB) |
| --- | --- | --- |
| 数据源 | `githubarchive.day.*` | `data.gharchive.org/*.json.gz` |
| 外部依赖 | GCP 账号、`gcloud`、`google-cloud-bigquery` | 仅需 Python + 公网 |
| 单次成本 | 扫表数十 GB,可能产生 BigQuery 费用 | 首次 600–700 MB 流量,之后稳态 ~30 MB |
| 历史能力 | 仅一次性查询 | 本地累积 1 年 hourly 倒排索引 |
| 分析能力 | 一条 SQL | star 曲线 / 任意日 Top / 加速度榜 / 黑马 / 幽灵仓库 |
| 运行频率 | 通常每天 1 次 | 推荐每小时 1 次,增量极小 |

---

## 🧱 项目结构

```
github-hunter/
├── workspace.py          # 自动建目录 + .env 模板 + 路径锚定
├── main.py               # ingest:GH Archive → .cache/,产出 24h 滑窗 result.csv
├── analyze.py            # 离线分析库:DuckDB SQL 跑在 .cache/ 上
├── daily_report.py       # 每日报告 + 可选 AI 摘要 + 可选 Webhook 推送
├── requirements.txt
├── .env                  # 首次运行自动生成模板,填 token 后即可使用
├── .gitignore            # 自动生成,默认忽略 .cache / result / reports
├── .cache/               # 自动创建,hourly parquet(每文件 1–3 MB)
├── result/               # main.py 产出,result_YYYY-MM-DD.csv
├── reports/              # daily_report.py 产出,csv + md
└── web/public/results/   # 给前端消费的 result.csv 副本(可选)
```

---

## ⚡ 快速开始

```bash
# 1. 安装依赖
cd e:\mysoftware
git clone https://github.com/chmod777john/github-hunter
cd github-hunter-local
uv venv --python 3.13.1  #默认会在当前目录创建 .venv 文件夹
.venv\Scripts\activate  #激活虚拟环境
uv pip install -r requirements.txt

# 2. 首次运行(会自动建好所有目录与 .env 模板,然后停下来让你填 token)
python main.py

# 3. 编辑 .env,填入 GH_TOKEN(必填) 与 OPENROUTER_API_KEY(可选)
# .env 路径: 项目根目录/.env
#或
$env:GH_TOKEN="your github token"
$env:OPENROUTER_API_KEY="your openrouter api key" 
$env:OPENROUTER_MODEL="openrouter/free"

# 4. 正式跑
python main.py               # ingest + 24h 滑窗,产出 result/result_YYYY-MM-DD.csv
python analyze.py            # 命令行直接预览加速度榜 / 黑马榜
python daily_report.py       # 生成 reports/daily_YYYY-MM-DD.md
```

**首次完整 ingest** 约下载 600–700 MB(24 个 hourly 文件),耗时 3–5 分钟;**第二次起**只下载新进窗口的 1–2 个文件,通常 30 秒内完成。

---

## 🔑 环境变量

所有变量集中在项目根目录的 `.env` 中(由首次运行自动生成模板)。

| 变量 | 是否必填 | 说明 |
| --- | --- | --- |
| `GH_TOKEN` | **必填** | [GitHub PAT](https://github.com/settings/tokens),勾 `public_repo` 只读即可 |
| `OPENROUTER_API_KEY` | 可选 | 用于生成项目 AI 总结与日报开篇。留空则自动跳过 |
| `REPORT_WEBHOOK_URL` | 可选 | 日报推送 webhook(企业微信 / Telegram / 通用) |
| `REPORT_WEBHOOK_STYLE` | 可选 | `wecom` / `tg` / `raw`,默认 `raw` |
| `HUNTER_HOME` | 可选 | 工作目录绝对路径,优先级高于 `cwd`,用于定时任务锚定 |
| `HUNTER_AUTO_BOOTSTRAP` | 可选 | `0` 可禁用 import 时的自动目录创建 |

---

## 🛰️ 数据流与缓存

整套流程的核心是把 GH Archive 的 hourly 文件**只解析一次、永久落盘**。

```
 GH Archive (.json.gz)
        │
        ▼  解析 WatchEvent → Counter(repo_name → count)
 .cache/YYYY-MM-DD-H.parquet     (~1–3 MB / hour)
        │
        ├─────►  main.py:最近 24 小时 → result.csv
        │
        └─────►  analyze.py:DuckDB SQL 任意时段聚合
                    │
                    └─►  daily_report.py:reports/*.csv + daily.md
```

**完结判定**:某小时距当前 UTC ≥ 2 小时才被认为"已完结",才会落盘;否则只在内存里参与本次聚合,下次再下载校验。这避免了把还在续传的 gzip 缓存成永久脏数据。

**缓存清理**:`KEEP_DAYS=365`,超过一年的旧 parquet 会被 `prune_cache()` 自动删除。一年合计约 8760 个文件、10–25 GB,普通 SSD 完全装得下。

---

## 🧪 离线分析能力(`analyze.py`)

所有函数共享一个 DuckDB 视图 `events(hour, repo_name, count)`,在 `.cache/*.parquet` 上原地执行 SQL,无需预合并文件。

```python
from analyze import (
    star_curve, top_n_on_day, top_n_on_week,
    fast_growing, acceleration_board, ghost_repo_candidates,
)

# 1) 单仓库 star 增长曲线(默认最近 90 天,按日聚合)
star_curve("Tencent/HunyuanVideo", freq="day")

# 2) 历史任意一天 Top 100
top_n_on_day("2026-05-13", n=100)

# 3) 任意一周 Top 100
top_n_on_week("2026-05-11", n=100)   # week_start 必须是周一(可选语义)

# 4) 连续 3 天每天 >= 50 stars 的"黑马"(回看 14 天)
fast_growing(streak_days=3, daily_threshold=50, lookback_days=14)

# 5) 今日 vs 过去 7 日均值的加速度榜
acceleration_board(min_today=20, top_n=100)

# 6) 幽灵仓库候选:有 stars 但 GraphQL 查不到(被删/被设私)
ghost_repo_candidates(lookback_days=7, min_stars=30)
```

---

## 📰 每日报告(`daily_report.py`)

每次运行会:

1. 在 `.cache/` 上跑四种分析,落到 `reports/{name}_YYYY-MM-DD.csv`;
2. 用 `to_markdown` 拼出一份 Markdown 日报;
3. 若设置了 `OPENROUTER_API_KEY`,用 LLM 在开头加一段 200 字总览;
4. 若设置了 `REPORT_WEBHOOK_URL`,推送到 webhook;否则只写文件。

预期效果：
```md
# GitHub Hunter 日报 · 2026-05-14

> # GitHub Hunter 日报 · 2026-05-14

今日开发者生态呈现出极强的“Agentic Workflow”转向，AI 智能体及其技能栈（Skills）成为绝对核心。最值得关注的是 **`mattpocock/skills`**，它凭借极高的日增量表现出强劲的爆发力；同时 **`anthropics/claude-for-legal`** 异军突起，显示出垂直领域 AI 应用的增长潜力。

**异常信号：** 榜单出现明显的“高并发爆发”现象，多个项目如 `openhuman` 和 `superpowers` 同时进入增长快车道，但由于“连续 3 天高速增长”榜单为空，且多项热门项目被列入“幽灵仓库候选”，暗示当前热潮可能存在短期流量驱动或项目生命周期极短的波动风险。

## 1. 昨日 Top 50(摘前 10)
| repo_name                         |   stars |
|:----------------------------------|--------:|
| tinyhumansai/openhuman            |     170 |
| mattpocock/skills                 |     150 |
| rohitg00/agentmemory              |      95 |
| NousResearch/hermes-agent         |      92 |
| obra/superpowers                  |      91 |
| Hmbown/DeepSeek-TUI               |      87 |
| multica-ai/andrej-karpathy-skills |      80 |
| yikart/AiToEarn                   |      75 |
| ruvnet/RuView                     |      73 |
| VoltAgent/awesome-design-md       |      73 |

## 2. 今日加速度榜(摘前 10)
| repo_name                         |   today_stars |     avg7 |   accel |
|:----------------------------------|--------------:|---------:|--------:|
| anthropics/claude-for-legal       |            32 |  8.42857 | 3.39394 |
| multica-ai/andrej-karpathy-skills |            26 | 11.4286  | 2.09195 |
| mattpocock/skills                 |            40 | 21.4286  | 1.78344 |
| obra/superpowers                  |            23 | 13       | 1.64286 |
| tinyhumansai/openhuman            |            28 | 24.2857  | 1.10734 |

## 3. 连续 3 天高速增长(摘前 10)
_(无数据)_

## 4. 幽灵仓库候选(摘前 10)
| repo_name                         |   stars |
|:----------------------------------|--------:|
| tinyhumansai/openhuman            |     198 |
| mattpocock/skills                 |     190 |
| obra/superpowers                  |     114 |
| rohitg00/agentmemory              |     113 |
| NousResearch/hermes-agent         |     107 |
| multica-ai/andrej-karpathy-skills |     106 |
| Hmbown/DeepSeek-TUI               |     101 |
| yikart/AiToEarn                   |      94 |
| anthropics/claude-for-legal       |      91 |
| github/spec-kit                   |      89 |

```


支持的 webhook 风格:

```env
# 企业微信群机器人
REPORT_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
REPORT_WEBHOOK_STYLE=wecom

# Telegram Bot
REPORT_WEBHOOK_URL=https://api.telegram.org/bot<token>/sendMessage?chat_id=<id>
REPORT_WEBHOOK_STYLE=tg

# 通用 JSON {"text": "..."}
REPORT_WEBHOOK_URL=https://your.endpoint/hook
REPORT_WEBHOOK_STYLE=raw
```

---

## 🕒 定时调度

### Windows 任务计划程序

**每小时 ingest**

- 程序或脚本:`python`
- 添加参数:`E:\path\to\github-hunter\main.py`
- 起始于:`E:\path\to\github-hunter`
- 触发器:每天 00:05,重复每 1 小时,持续 1 天,启用

**每日报告(国内 09:00 = UTC 01:00)**

- 程序或脚本:`python`
- 添加参数:`E:\path\to\github-hunter\daily_report.py`
- 起始于:`E:\path\to\github-hunter`
- 触发器:每天 09:00

如果任务调度器吞掉了 `cwd`,在系统环境变量里加 `HUNTER_HOME=E:\path\to\github-hunter` 即可,`workspace.py` 会强制把根目录锚定到这里。

### Linux / macOS (cron)

```cron
# 每小时 ingest
5 * * * * HUNTER_HOME=/opt/github-hunter /usr/bin/python3 /opt/github-hunter/main.py >> /var/log/hunter.log 2>&1

# 每日 09:00 报告
0 9 * * * HUNTER_HOME=/opt/github-hunter /usr/bin/python3 /opt/github-hunter/daily_report.py >> /var/log/hunter.log 2>&1
```

### GitHub Actions(零本地依赖)

把 `.cache/` 提交到一个私有仓库 / 用 [actions/cache](https://github.com/actions/cache) 持久化,定时任务即可在 GitHub 的免费 runner 上跑完整套流程。

---

## ❓ FAQ

**Q1. 第一次跑出现 `<Code>NoSuchKey</Code>` 怎么办?**
那是 GH Archive 在 S3 上的 404,通常因为请求了未来或刚刚结束的 1 小时(归档延迟 30–90 分钟)。`fetch_hour()` 对 404 是静默跳过的,不影响主流程。

**Q2. PowerShell 里 `curl -I` 卡住要 Uri?**
PowerShell 的 `curl` 是 `Invoke-WebRequest` 的别名,`-I` 不被识别。改用 `curl.exe -I <url>`,或 `Invoke-WebRequest -Method Head -Uri <url>`。

**Q3. `pip install dotenv` 装错了?**
正确包名是 `python-dotenv`,代码里 `import dotenv` 是对的。PyPI 上同名的 `dotenv` 是另一个不相关的小项目,**不要装**。

**Q4. 缓存目录越来越大怎么办?**
默认 `KEEP_DAYS=365` 自动清理。如果硬盘紧张,改成 90 或 180 即可;也可以每周末把 7 天前的 hourly 合并成 weekly parquet,文件数从几千降到几十。

**Q5. 想加 BigQuery 同步备份?**
仍然可以。`main.py` 的 ingest 完全是本地操作,你可以在 `prune_cache` 之后加一个 `bq load` 或 `gcloud storage cp` 步骤把 parquet 同步上去,与本地工作流不冲突。

---

## 项目更新
```powershell
type .gitignore
git init
git branch -M main
git add .
git status
git commit -m "feat: github-hunter local"
git remote add origin https://github.com/your-github-name/github-hunter-local.git

git push -u origin main

#设置代理
#根据你的代理协议填写
$env:HTTP_PROXY="http://127.0.0.1:3067"
$env:HTTPS_PROXY="http://127.0.0.1:3067"
git push -u origin main

git config --global http.proxy http://127.0.0.1:3067
git config --global https.proxy http://127.0.0.1:3067

#检查网络连接
Invoke-RestMethod -Uri http://httpbin.org/ip
git ls-remote https://github.com/your-github-name/github-hunter-local.git
```

### 修改同步到本地仓库和github
```python
#pip freeze > requirements.txt
mkdir -p .github/workflows
code-insiders .github/workflows/daily_report.yml

git status
git add .github/workflows/daily_report.yml
git commit -m "添加每日报告自动生成与Pages部署工作流"
git commit -m "索引页同时展示 Markdown 报告 和 CSV 数据文件的链接"
git commit -m "将 git add reports/ 改为 git add -f reports/:强制添加被 .gitignore 排除的文件。这样即使本地开发时不想提交报告，Actions 环境也能正常推送"
git commit -m "正确显示日报时间/csv文件"
git push
git pull origin main
git push origin main
#Git 会尝试自动合并远程和本地改动。如果有冲突，按提示解决即可（冲突很可能发生在 daily_report.yml 文件上，因为我们都修改了它）
git pull origin main --no-rebase

#about添加url
https://wzf9.github.io/github-hunter-local
code-insiders readme.md
# 编辑 README.md，添加上面的链接
git add README.md
git commit -m "docs: add GitHub Pages URL to README"
git push origin main

git status
git add build_website.py          # 新增的网站生成脚本
git add web/     # 生成的仪表盘页面（如果有）
git commit -m "feat: add website generator for GitHub Pages dashboard"
git push origin main

# 1. 获取远程最新状态
git fetch origin
# 2. 将本地提交“变基”到远程 main 分支之上（保持历史干净）
git pull --rebase origin main

# 如果出现冲突，需要手动解决冲突文件，然后：
#   git add <已解决的文件>
#   git rebase --continue

# 3. 推送本地变更到远程
git push origin main
```


## 🛣️ Roadmap

- [ ] **聚合搜索**:集成 ProductHunt / HackerNews / arXiv 数据源,做跨平台热度交叉验证。
- [ ] **README 深度评分**:用 LLM 对前 N 项目的 README 做"实际落地价值"打分。
- [ ] **DuckDB UI**:基于 `.cache/` 直接起一个本地 Web 面板,支持任意 SQL 查询与图表。
- [ ] **NFT/区块链存证**:把每日的"黑马预言"自动上链(对齐原版的时间戳预言玩法)。

---

## 📝 License

继承原仓库 [chmod777john/github-hunter](https://github.com/chmod777john/github-hunter) 的开源协议(MIT)。改造与本地化部分以同等协议发布。

---

## 🙏 致谢

- [chmod777john](https://github.com/chmod777john) —— 原版 github-hunter 的算法思路。
- [Ilya Grigorik / GH Archive](https://www.gharchive.org) —— 持续 10+ 年免费开放的 GitHub 公共事件流。
- [DuckDB](https://duckdb.org) —— 让"本地一份 parquet 目录当数据仓库用"成为可能。

## 📊 数据来源（Data Sources）

本项目的所有热度信号均来自以下公开数据源，特此致谢并标注：

| 数据源 | 用途 | 协议 / 服务条款 |
| --- | --- | --- |
| [GH Archive](https://www.gharchive.org) | 提供 GitHub 全量事件流的 hourly `.json.gz` 归档 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| [GitHub REST API](https://docs.github.com/en/rest) | 拉取仓库元数据（描述、语言、Stars 等） | 遵守 [GitHub Acceptable Use Policies](https://docs.github.com/en/site-policy/acceptable-use-policies) |
| [OpenRouter](https://openrouter.ai) (可选) | 生成日报 AI 摘要 | 遵守 [OpenRouter Terms](https://openrouter.ai/terms)，使用者自备 API Key |

> Data sourced from GH Archive (licensed under CC BY 4.0) and the GitHub REST API.
> AI summaries (when enabled) are generated via OpenRouter using the user's own API key.

## ⚠️ 免责声明（Disclaimer）

1. **学习与研究用途**：本项目仅供学习、研究与个人技术验证，不构成任何投资、商业或决策建议。基于本项目分析结果作出的任何判断与行动，使用者需自行承担全部责任。
2. **数据准确性**：原始数据来自 GH Archive 与 GitHub Public API，可能因归档延迟、API 限流、上游事件丢失等原因出现遗漏或偏差。本项目不对数据的完整性、准确性、时效性作任何明示或暗示的保证。
3. **AI 生成内容标识**：日报中的"项目摘要"与"开篇导读"由大语言模型自动生成，可能存在事实性错误或臆测，**仅供参考**。请结合原始仓库 README 与实际代码自行核实。生成内容遵循 [《生成式人工智能服务管理暂行办法》](https://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm) 的标识要求。
4. **第三方仓库内容**：本项目仅做公开统计，不对所列出仓库的代码质量、安全性、合法性背书。"幽灵仓库黑名单"等启发式判定结果可能存在误判，请勿据此对相关账号或代码作出定性结论。
5. **使用风险自担**：依据 MIT 协议，本软件按"原样"提供，作者不对使用过程中产生的任何直接或间接损失承担责任。

> This project is provided **​"AS IS"​** under the MIT License, for educational and research purposes only.
> Outputs (including AI-generated summaries and heuristic blacklists) are advisory in nature and must be independently verified before use.

*内容由 AI 生成仅供参考*