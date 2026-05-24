#!/usr/bin/env python3
"""生成 GitHub Pages 仪表盘：展示最近的 result.csv 和 reports 中的 CSV/MD 链接"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import pandas as pd
import shutil

ROOT = Path(__file__).parent
RESULT_DIR = ROOT / "result"
REPORTS_DIR = ROOT / "reports"
WEB_PUBLIC = ROOT / "web" / "public"
RESULTS_WEB = WEB_PUBLIC / "results"   # 存放 result.csv 副本
INDEX_PATH = WEB_PUBLIC / "index.html"

def copy_latest_result():
    """将最新的 result_*.csv 复制为 result.csv"""
    result_files = sorted(RESULT_DIR.glob("result_*.csv"), reverse=True)
    if not result_files:
        print("未找到 result_*.csv")
        return None
    latest = result_files[0]
    shutil.copy(latest, RESULTS_WEB / "result.csv")
    print(f"已复制 {latest.name} -> web/public/results/result.csv")
    return latest

def get_report_files():
    """返回 reports 目录下的 CSV 和 MD 文件列表（按修改时间倒序）"""
    csv_files = sorted(REPORTS_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    md_files = sorted(REPORTS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return csv_files, md_files

def generate_html(result_file: Path | None, csv_files: list[Path], md_files: list[Path]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = ""
    # 展示最新的 result.csv 链接
    if result_file:
        mtime = datetime.fromtimestamp(result_file.stat().st_mtime)
        rows += f"""
        <tr>
            <td><strong>📊 24h 热点榜单 (Top 1000)</strong></td>
            <td><a href="results/result.csv">result.csv</a></td>
            <td>{mtime.strftime('%Y-%m-%d %H:%M')}</td>
        </tr>
        """
    # 展示 reports 中的 CSV 和 MD
    for csv in csv_files[:10]:
        mtime = datetime.fromtimestamp(csv.stat().st_mtime)
        rows += f"""
        <tr>
            <td>📈 {csv.stem.replace('_', ' ')}</td>
            <td><a href="../reports/{csv.name}">{csv.name}</a></td>
            <td>{mtime.strftime('%Y-%m-%d %H:%M')}</td>
        </tr>
        """
    for md in md_files[:10]:
        mtime = datetime.fromtimestamp(md.stat().st_mtime)
        rows += f"""
        <tr>
            <td>📝 日报 Markdown</td>
            <td><a href="../reports/{md.name}">{md.name}</a></td>
            <td>{mtime.strftime('%Y-%m-%d %H:%M')}</td>
        </tr>
        """
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GitHub Hunter 本地版 - 实时趋势看板</title>
    <style>
        body {{ font-family: system-ui, 'Segoe UI', Roboto; max-width: 1200px; margin: 2rem auto; padding: 0 1rem; }}
        h1 {{ color: #24292f; border-bottom: 1px solid #e1e4e8; padding-bottom: 0.3rem; }}
        table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
        th, td {{ border: 1px solid #dfe2e5; padding: 0.5rem; text-align: left; }}
        th {{ background-color: #f6f8fa; }}
        a {{ color: #0366d6; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .footer {{ margin-top: 2rem; font-size: 0.8rem; color: #586069; border-top: 1px solid #e1e4e8; padding-top: 1rem; }}
    </style>
</head>
<body>
    <h1>🚀 GitHub Hunter · 本地版动态看板</h1>
    <p>数据更新于: {now} (UTC+8)</p>
    <p><strong>说明</strong>：点击链接可下载原始 CSV 或查看 Markdown 日报。<br>
       排行榜基于最近24小时 GitHub WatchEvent 统计 + DuckDB 离线分析。</p>
    <table>
        <thead>
            <tr><th>类别</th><th>文件 / 报告</th><th>最后修改时间</th></tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
    <div class="footer">
        📡 数据源：GH Archive (CC BY 4.0) + GitHub REST API<br>
        🤖 AI 摘要由 OpenRouter 生成（若已配置）<br>
        <a href="https://github.com/wzf9/github-hunter-local">GitHub 仓库</a>
    </div>
</body>
</html>"""
    return html

def main():
    # 1. 确保 web/public/results 存在
    RESULTS_WEB.mkdir(parents=True, exist_ok=True)
    # 2. 复制最新的 result CSV
    latest_result = copy_latest_result()
    # 3. 获取 reports 下的文件
    csv_files, md_files = get_report_files()
    # 4. 生成 HTML
    html_content = generate_html(latest_result, csv_files, md_files)
    INDEX_PATH.write_text(html_content, encoding="utf-8")
    print(f"✅ 已生成仪表盘: {INDEX_PATH}")

if __name__ == "__main__":
    main()