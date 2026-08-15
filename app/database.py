from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import CACHE_TTL_HOURS, DB_PATH

SEASON_TTL_SECONDS = CACHE_TTL_HOURS * 3600

SCHEMA = """
CREATE TABLE IF NOT EXISTS anime_cache (
    id INTEGER PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS season_cache (
    year INTEGER NOT NULL,
    season TEXT NOT NULL,
    fetched_at INTEGER NOT NULL,
    PRIMARY KEY (year, season)
);

CREATE TABLE IF NOT EXISTS watch_records (
    anime_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'want_to_watch',
    progress INTEGER NOT NULL DEFAULT 0,
    personal_score INTEGER,
    notes TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (anime_id) REFERENCES anime_cache(id)
);

CREATE TABLE IF NOT EXISTS preferences (
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (kind, value)
);

CREATE TABLE IF NOT EXISTS search_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT,
    genres TEXT,
    season TEXT,
    year INTEGER,
    result_count INTEGER,
    created_at INTEGER NOT NULL
);
"""

STATUSES = ("want_to_watch", "watching", "completed", "dropped")


def now_ts() -> int:
    return int(time.time())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | Path = DB_PATH) -> None:
    with _conn(db_path) as conn:
        conn.executescript(SCHEMA)


class Database:
    def __init__(self, db_path: str | Path = DB_PATH) -> None:
        self.db_path = str(db_path)

    def _conn(self) -> sqlite3.Connection:
        return _conn(self.db_path)

    def now_ts(self) -> int:
        return now_ts()

    # ---------- anime cache ----------
    # Authority ranking for title_zh sources. Wikidata-derived names win over
    # heuristic/synonym-derived ones, so re-normalizing a season from AniList
    # never clobbers a translation we already resolved.
    ZH_PRIORITY = {"wikidata": 3, "zhwiki": 2, "synonym": 2, "synonym_fallback": 2, "none": 1}

    def upsert_anime(self, items: list[dict]) -> int:
        with _conn(self.db_path) as conn:
            for item in items:
                existing = conn.execute(
                    "SELECT data FROM anime_cache WHERE id = ?", (item["id"],)
                ).fetchone()
                merged = dict(item)
                if existing:
                    old = json.loads(existing["data"])
                    merged = self._merge_zh(old, item)
                conn.execute(
                    "INSERT OR REPLACE INTO anime_cache (id, data, updated_at) "
                    "VALUES (?, ?, ?)",
                    (merged["id"], json.dumps(merged, ensure_ascii=False), now_ts()),
                )
        return len(items)

    @staticmethod
    def _merge_zh(old: dict, new: dict) -> dict:
        """Keep the most authoritative existing Chinese fields across re-fetches."""
        merged = dict(new)

        def keep_better(old_v, old_s, new_v, new_s):
            old_prio = Database.ZH_PRIORITY.get(old_s, 1)
            new_prio = Database.ZH_PRIORITY.get(new_s, 1)
            if old_v and (not new_v or old_prio >= new_prio):
                return old_v, old_s
            return new_v, new_s

        merged["title_zh"], merged["title_zh_source"] = keep_better(
            old.get("title_zh"), old.get("title_zh_source"),
            new.get("title_zh"), new.get("title_zh_source"),
        )
        merged["synopsis_zh"], merged["synopsis_zh_source"] = keep_better(
            old.get("synopsis_zh"), old.get("synopsis_zh_source"),
            new.get("synopsis_zh"), new.get("synopsis_zh_source"),
        )
        if not merged.get("title_zh_attempted") and old.get("title_zh_attempted"):
            merged["title_zh_attempted"] = True
        if not merged.get("title_zh_source"):
            merged["title_zh_source"] = old.get("title_zh_source")
        if not merged.get("synopsis_zh_source"):
            merged["synopsis_zh_source"] = old.get("synopsis_zh_source")
        return merged

    def get_anime(self, anime_id: int) -> dict | None:
        with _conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT data FROM anime_cache WHERE id = ?", (anime_id,)
            ).fetchone()
        return json.loads(row["data"]) if row else None

    def anime_ids(self) -> set[int]:
        with _conn(self.db_path) as conn:
            rows = conn.execute("SELECT id FROM anime_cache").fetchall()
        return {r["id"] for r in rows}

    def mark_season_fetched(self, year: int, season: str) -> None:
        with _conn(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO season_cache (year, season, fetched_at) "
                "VALUES (?, ?, ?)",
                (year, season.upper(), now_ts()),
            )

    def is_season_fresh(self, year: int, season: str) -> bool:
        with _conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT fetched_at FROM season_cache WHERE year = ? AND season = ?",
                (year, season.upper()),
            ).fetchone()
        if not row:
            return False
        return (now_ts() - row["fetched_at"]) < SEASON_TTL_SECONDS

    # ---------- filtering (regex/sql on cached json) ----------
    def query_anime(
        self,
        *,
        season: str | None = None,
        year: int | None = None,
        genres: list[str] | None = None,
        min_score: int | None = None,
        search: str | None = None,
        sort_by: str = "popularity",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """Filter anime from the local cache. Search is a fuzzy keyword match."""
        rows = self._load_all_anime()
        items = [json.loads(r["data"]) for r in rows]

        if season:
            items = [i for i in items if (i.get("season") or "").upper() == season.upper()]
        if year is not None:
            items = [i for i in items if i.get("season_year") == int(year)]
        if genres:
            gs = {g.lower() for g in genres if g}
            items = [
                i for i in items
                if gs.intersection({g.lower() for g in i.get("genres") or []})
            ]
        if min_score is not None:
            items = [i for i in items if (i.get("mean_score") or 0) >= int(min_score)]
        if search:
            kw = search.strip().lower()
            if kw:
                matched = []
                for i in items:
                    hay = " ".join(
                        filter(
                            None,
                            [
                                i.get("title_zh"),
                                i.get("title_romaji"),
                                i.get("title_english"),
                                i.get("title_native"),
                                " ".join(i.get("genres") or []),
                                " ".join(i.get("tags") or []),
                                i.get("synopsis") or "",
                                i.get("synopsis_zh") or "",
                            ],
                        )
                    ).lower()
                    if kw in hay:
                        matched.append(i)
                items = matched

        total = len(items)
        sort_keys = {
            "score": lambda i: (i.get("mean_score") or 0),
            "popularity": lambda i: (i.get("popularity") or 0),
            "trending": lambda i: (i.get("trending") or 0),
            "favourites": lambda i: (i.get("favourites") or 0),
            "title": lambda i: (
                i.get("title_romaji") or i.get("title_english") or ""
            ).lower(),
            "episodes": lambda i: (i.get("episodes") or 0),
        }
        key = sort_keys.get(sort_by, sort_keys["popularity"])
        reverse = sort_by != "title"
        items.sort(key=key, reverse=reverse)
        return items[offset : offset + limit], total

    def _load_all_anime(self) -> list[sqlite3.Row]:
        with _conn(self.db_path) as conn:
            return conn.execute("SELECT data FROM anime_cache").fetchall()

    def all_titles_sorted(self, limit: int = 100) -> list[dict]:
        """Best rating-first list of all cached anime (for populating dropdowns)."""
        return self.query_anime(sort_by="score", limit=limit)[0]

    # ---------- watch records ----------
    def set_watch_record(
        self,
        anime_id: int,
        status: str | None = None,
        progress: int | None = None,
        personal_score: int | None = None,
        notes: str | None = None,
    ) -> dict:
        if status is not None and status not in STATUSES:
            raise ValueError(f"Invalid status: {status}")
        if personal_score is not None and not (0 <= int(personal_score) <= 10):
            raise ValueError("personal_score must be between 0 and 10")
        ts = now_ts()
        with _conn(self.db_path) as conn:
            existing = conn.execute(
                "SELECT * FROM watch_records WHERE anime_id = ?", (anime_id,)
            ).fetchone()
            if existing:
                cur = dict(existing)
                new_status = status if status is not None else cur["status"]
                new_progress = (
                    progress if progress is not None else cur["progress"]
                )
                new_score = (
                    personal_score
                    if personal_score is not None
                    else cur["personal_score"]
                )
                new_notes = (
                    notes if notes is not None else cur.get("notes")
                )
                conn.execute(
                    "UPDATE watch_records SET status = ?, progress = ?, "
                    "personal_score = ?, notes = ?, updated_at = ? "
                    "WHERE anime_id = ?",
                    (
                        new_status,
                        int(new_progress),
                        new_score,
                        new_notes,
                        ts,
                        anime_id,
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO watch_records (anime_id, status, progress, "
                    "personal_score, notes, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        anime_id,
                        status or "want_to_watch",
                        int(progress or 0),
                        personal_score,
                        notes,
                        ts,
                        ts,
                    ),
                )
        return self.get_watch_record(anime_id)

    def get_watch_record(self, anime_id: int) -> dict | None:
        with _conn(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM watch_records WHERE anime_id = ?", (anime_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_watchlist(self, status: str | None = None) -> list[dict]:
        with _conn(self.db_path) as conn:
            q = (
                "SELECT * FROM watch_records"
                + (" WHERE status = ?" if status else "")
                + " ORDER BY updated_at DESC"
            )
            params = (status,) if status else ()
            rows = conn.execute(q, params).fetchall()
        result = []
        for r in rows:
            rec = dict(r)
            anime = self.get_anime(rec["anime_id"])
            rec["anime"] = anime or {}
            rec["updated_at_ts"] = rec["updated_at"]
            result.append(rec)
        return result

    def delete_watch_record(self, anime_id: int) -> bool:
        with _conn(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM watch_records WHERE anime_id = ?", (anime_id,)
            )
        return cur.rowcount > 0

    # ---------- preferences ----------
    def add_preference(self, kind: str, value: str) -> None:
        kind = kind.strip().lower()
        value = value.strip()
        if kind not in ("genre", "keyword"):
            raise ValueError("kind must be 'genre' or 'keyword'")
        if not value:
            raise ValueError("value cannot be empty")
        with _conn(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO preferences (kind, value, created_at) "
                "VALUES (?, ?, ?)",
                (kind, value, now_ts()),
            )

    def remove_preference(self, kind: str, value: str) -> None:
        with _conn(self.db_path) as conn:
            conn.execute(
                "DELETE FROM preferences WHERE kind = ? AND value = ?",
                (kind.strip().lower(), value.strip()),
            )

    def get_preferences(self) -> dict[str, list[str]]:
        with _conn(self.db_path) as conn:
            rows = conn.execute(
                "SELECT kind, value FROM preferences ORDER BY created_at"
            ).fetchall()
        prefs: dict[str, list[str]] = {"genre": [], "keyword": []}
        for r in rows:
            prefs.setdefault(r["kind"], []).append(r["value"])
        return prefs

    # ---------- search log ----------
    def log_search(
        self,
        query: str | None,
        genres: str | None,
        season: str | None,
        year: int | None,
        result_count: int,
    ) -> None:
        with _conn(self.db_path) as conn:
            conn.execute(
                "INSERT INTO search_log (query, genres, season, year, "
                "result_count, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    query,
                    genres,
                    season,
                    year,
                    result_count,
                    now_ts(),
                ),
            )