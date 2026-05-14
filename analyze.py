"""
github-hunter 离线分析层
依赖 .cache/*.parquet (由 main.py 产出)
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import duckdb
import pandas as pd

from workspace import ensure_workspace
from github_api import fetch_repo_details_parallel

PATHS = ensure_workspace(verbose=False)
CACHE_DIR = PATHS["CACHE_DIR"]
GLOB      = (CACHE_DIR / "*.parquet").as_posix()

_con = duckdb.connect(database=":memory:")
_con.execute("PRAGMA threads=8")
_view_registered = False


def _register_view() -> None:
    global _view_registered
    if _view_registered:
        return
    _con.execute(f"""
        CREATE OR REPLACE VIEW events AS
        SELECT
            strptime(
                regexp_replace(filename, '^.*[/\\\\]', ''),
                '%Y-%m-%d-%H.parquet'
            ) AS hour,
            repo_name,
            count
        FROM read_parquet('{GLOB}', filename = true)
    """)
    _view_registered = True


def refresh_view() -> None:
    global _view_registered
    _view_registered = False
    _register_view()


# ── 1. 单仓库 star 增长曲线 ──────────────────────────────────
def star_curve(repo: str, freq: str = "day",
               since: datetime | None = None,
               until: datetime | None = None) -> pd.DataFrame:
    _register_view()
    until = until or datetime.now(timezone.utc)
    since = since or until - timedelta(days=90)
    truncate = {"hour": "hour", "day": "day", "week": "week"}[freq]
    df = _con.execute(f"""
        SELECT date_trunc('{truncate}', hour) AS bucket,
               SUM(count)                     AS stars
        FROM events
        WHERE repo_name = ? AND hour >= ? AND hour < ?
        GROUP BY bucket ORDER BY bucket
    """, [repo, since, until]).df()
    if not df.empty:
        df["cum_stars"] = df["stars"].cumsum()
    return df


# ── 2. 任意时段 Top N ───────────────────────────────────────
def top_n_in_range(since: datetime, until: datetime, n: int = 100) -> pd.DataFrame:
    _register_view()
    return _con.execute("""
        SELECT repo_name, SUM(count) AS stars
        FROM events WHERE hour >= ? AND hour < ?
        GROUP BY repo_name ORDER BY stars DESC LIMIT ?
    """, [since, until, n]).df()

def top_n_on_day(date: str, n: int = 100) -> pd.DataFrame:
    d = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return top_n_in_range(d, d + timedelta(days=1), n)

def top_n_on_week(week_start: str, n: int = 100) -> pd.DataFrame:
    d = datetime.strptime(week_start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return top_n_in_range(d, d + timedelta(days=7), n)


# ── 3. 连续 N 天高速增长 ─────────────────────────────────────
def fast_growing(streak_days: int = 3, daily_threshold: int = 50,
                 lookback_days: int = 14) -> pd.DataFrame:
    _register_view()
    until = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    since = until - timedelta(days=lookback_days)
    return _con.execute("""
    WITH daily AS (
        SELECT date_trunc('day', hour) AS day,
               repo_name, SUM(count) AS daily_stars
        FROM events WHERE hour >= ? AND hour < ?
        GROUP BY day, repo_name
    ),
    flagged AS (
        SELECT *, (daily_stars >= ?) AS hot,
               ROW_NUMBER() OVER (PARTITION BY repo_name ORDER BY day) -
               ROW_NUMBER() OVER (PARTITION BY repo_name, (daily_stars >= ?) ORDER BY day)
               AS grp
        FROM daily
    ),
    streaks AS (
        SELECT repo_name, grp,
               COUNT(*)         AS streak_len,
               SUM(daily_stars) AS streak_stars,
               MIN(day)         AS streak_start,
               MAX(day)         AS streak_end
        FROM flagged WHERE hot
        GROUP BY repo_name, grp
        HAVING COUNT(*) >= ?
    )
    SELECT repo_name, streak_len, streak_stars, streak_start, streak_end
    FROM streaks ORDER BY streak_stars DESC
    """, [since, until, daily_threshold, daily_threshold, streak_days]).df()


# ── 4. 加速度榜:今日 vs 7 日均 ───────────────────────────────
def acceleration_board(min_today: int = 20, top_n: int = 100) -> pd.DataFrame:
    _register_view()
    today = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return _con.execute("""
    WITH today AS (
        SELECT repo_name, SUM(count) AS today_stars
        FROM events WHERE hour >= ? AND hour < ?
        GROUP BY repo_name
    ),
    week AS (
        SELECT repo_name, SUM(count) / 7.0 AS avg7
        FROM events WHERE hour >= ? AND hour < ?
        GROUP BY repo_name
    )
    SELECT t.repo_name, t.today_stars,
           COALESCE(w.avg7, 0) AS avg7,
           t.today_stars / (COALESCE(w.avg7, 0) + 1) AS accel
    FROM today t LEFT JOIN week w USING (repo_name)
    WHERE t.today_stars >= ?
    ORDER BY accel DESC LIMIT ?
    """, [today, today + timedelta(days=1),
          today - timedelta(days=7), today,
          min_today, top_n]).df()


# ── 5. 幽灵仓库候选 ─────────────────────────────────────────
def ghost_repo_candidates(lookback_days: int = 7,
                          min_stars: int = 30) -> pd.DataFrame:
    _register_view()
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=lookback_days)
    candidates = _con.execute("""
        SELECT repo_name, SUM(count) AS stars
        FROM events WHERE hour >= ? AND hour < ?
        GROUP BY repo_name HAVING SUM(count) >= ?
        ORDER BY stars DESC
    """, [since, until, min_stars]).df()

    enriched = fetch_repo_details_parallel(candidates.copy())
    ghosts = enriched[enriched["created_at"].isna()].copy()
    return ghosts[["repo_name", "stars"]].sort_values("stars", ascending=False)


if __name__ == "__main__":
    pd.set_option("display.max_rows", 30)
    print("""
== acceleration_board(top 20) ==""")
    print(acceleration_board(min_today=20, top_n=20))

    print("""
== fast_growing(streak=3, >=50/d, 14d) ==""")
    print(fast_growing(3, 50, 14).head(20))
