from __future__ import annotations

import json
import threading
import time

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .anilist import SEASONS, AniListClient, AniListError, current_season
from .config import STATIC_DIR
from .database import STATUSES, Database, init_db
from .wikimedia import ResolutionError, resolve_chinese_title

app = FastAPI(title="AniTrack", version="1.0.0")
db = Database()
anilist = AniListClient()

# Background title-translation sync state.
_title_lock = threading.Lock()
_title_state: dict = {
    "running": False,
    "total": 0,
    "done": 0,
    "hit": 0,
    "miss": 0,
    "started_at": None,
    "message": "",
}


class WatchRecordIn(BaseModel):
    status: str | None = None
    progress: int | None = Field(default=None, ge=0)
    personal_score: int | None = Field(default=None, ge=0, le=10)
    notes: str | None = None


class PreferenceIn(BaseModel):
    kind: str
    value: str


def _fetch_season(year: int, season: str, force: bool = False) -> None:
    """Ensure a season's anime is cached, fetching from AniList if stale."""
    season = season.upper()
    if not force and db.is_season_fresh(year, season):
        return
    try:
        media = anilist.fetch_all_seasonal(year, season)
    except AniListError as exc:
        # Fall back to existing cache if we have any data at all.
        if not db._load_all_anime():
            raise HTTPException(502, f"AniList unavailable: {exc}")
        return
    db.upsert_anime(media)
    db.mark_season_fetched(year, season)


def _merge_watch(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        rec = db.get_watch_record(it["id"])
        it["watch_status"] = rec["status"] if rec else None
        it["my_progress"] = rec["progress"] if rec else 0
        it["my_score"] = rec["personal_score"] if rec else None
        it["my_notes"] = rec["notes"] if rec else None
        out.append(it)
    return out


def _resolve_season(year: int | None, season: str | None) -> tuple[int, str]:
    if season is None:
        return current_season()
    season = season.upper()
    if season not in SEASONS:
        raise HTTPException(400, f"season must be one of {SEASONS}")
    if year is None:
        year, _ = current_season()
    return year, season


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/season")
def season_anime(
    year: int | None = None,
    season: str | None = None,
    force: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    year, season = _resolve_season(year, season)
    _fetch_season(year, season, force)
    items, total = db.query_anime(
        season=season, year=year, sort_by="popularity", limit=limit, offset=offset
    )
    return {
        "year": year,
        "season": season.upper(),
        "total": total,
        "items": _merge_watch(items),
    }


@app.get("/api/search")
def search_anime(
    q: str | None = None,
    genres: list[str] | None = Query(default=None),
    min_score: int | None = Query(default=None, ge=0, le=100),
    sort_by: str = Query(default="popularity"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Search the local cache; returns a hint if no season is loaded yet."""
    if not db._load_all_anime():
        return {
            "total": 0,
            "items": [],
            "hint": "No anime cached yet. Call GET /api/season first, then search.",
            "query": q,
            "genres": genres,
        }
    items, total = db.query_anime(
        genres=genres,
        min_score=min_score,
        search=q,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )
    db.log_search(q, ",".join(genres or []), None, None, total)
    return {"total": total, "items": _merge_watch(items), "query": q, "genres": genres}


@app.get("/api/top10")
def top10(
    year: int | None = None,
    season: str | None = None,
    force: bool = False,
):
    """Top 10 ranking by score weighted with popularity."""
    year, season = _resolve_season(year, season)
    _fetch_season(year, season, force)
    items, _ = db.query_anime(
        season=season, year=year, sort_by="popularity", limit=1000
    )
    items = [i for i in items if not i.get("is_adult")]

    def rank_key(i: dict) -> float:
        score = i.get("mean_score") or 0
        pop = i.get("popularity") or 0
        return score * (1 + (pop / 100000.0))

    ranked_items = sorted(items, key=rank_key, reverse=True)[:10]
    ranked = []
    for idx, i in enumerate(ranked_items, 1):
        rec = db.get_watch_record(i["id"])
        ranked.append(
            {
                "rank": idx,
                "media": i,
                "watch_status": rec["status"] if rec else None,
            }
        )
    return {
        "year": year,
        "season": season.upper(),
        "count": len(ranked),
        "ranked": ranked,
        "score_formula": "mean_score weighted by popularity",
    }


@app.get("/api/anime/{anime_id}")
def anime_detail(anime_id: int):
    media = db.get_anime(anime_id)
    if not media:
        raise HTTPException(404, "Anime not in cache")
    rec = db.get_watch_record(anime_id)
    media["watch_status"] = rec["status"] if rec else None
    media["my_progress"] = rec["progress"] if rec else 0
    media["my_score"] = rec["personal_score"] if rec else None
    media["my_notes"] = rec["notes"] if rec else None
    return media


@app.put("/api/anime/{anime_id}/watch")
def update_watch(anime_id: int, payload: WatchRecordIn):
    if not db.get_anime(anime_id):
        raise HTTPException(404, "Anime not in cache")
    try:
        rec = db.set_watch_record(
            anime_id,
            status=payload.status,
            progress=payload.progress,
            personal_score=payload.personal_score,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    rec["anime"] = db.get_anime(anime_id)
    return rec


@app.delete("/api/anime/{anime_id}/watch")
def delete_watch(anime_id: int):
    ok = db.delete_watch_record(anime_id)
    if not ok:
        raise HTTPException(404, "No watch record for that anime")
    return {"deleted": anime_id}


@app.get("/api/watchlist")
def watchlist(status: str | None = Query(default=None)):
    if status is not None and status not in STATUSES:
        raise HTTPException(400, f"status must be one of {STATUSES}")
    return db.get_watchlist(status)


@app.get("/api/genres")
def genres():
    items, _ = db.query_anime(limit=10000)
    freq: dict[str, int] = {}
    for i in items:
        for g in i.get("genres") or []:
            freq[g] = freq.get(g, 0) + 1
    return {"genres": sorted(freq, key=lambda g: (-freq[g], g))}


@app.get("/api/preferences")
def get_preferences():
    return {"preferences": db.get_preferences()}


@app.post("/api/preferences")
def add_preference(payload: PreferenceIn):
    try:
        db.add_preference(payload.kind, payload.value)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"preferences": db.get_preferences()}


@app.delete("/api/preferences")
def remove_preference(kind: str = Query(...), value: str = Query(...)):
    db.remove_preference(kind, value)
    return {"preferences": db.get_preferences()}


@app.get("/api/search/preferences")
def search_preferences(
    min_score: int | None = Query(default=None, ge=0, le=100),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Search using saved genre/keyword preferences."""
    prefs = db.get_preferences()
    genres = prefs.get("genre", [])
    keywords = prefs.get("keyword", [])
    query = " ".join(keywords) or None
    items, _ = db.query_anime(
        genres=genres, min_score=min_score, search=query, sort_by="score", limit=limit
    )
    return {"preferences": prefs, "total": len(items), "items": _merge_watch(items)}


def _title_worker(force: bool = False, recheck: bool = False) -> None:
    with _title_lock:
        _title_state.update(running=True, total=0, done=0, hit=0, miss=0, skipped=0)
        rows = db._load_all_anime()
        pending = []
        for row in rows:
            item = json.loads(row["data"])
            retries = item.get("zh_retries") or 0
            if force:
                pending.append(item)
            elif recheck:
                if not item.get("title_zh") and retries < 3:
                    pending.append(item)
            elif not item.get("title_zh_attempted"):
                pending.append(item)
        _title_state["total"] = len(pending)
    if len(pending) == 0:
        with _title_lock:
            _title_state.update(
                running=False, done=0, message="所有已快取作品都已具備中文名稱"
            )
        return

    for idx, item in enumerate(pending, 1):
        try:
            zh = resolve_chinese_title(
                item.get("title_native"),
                item.get("title_english"),
                item.get("title_romaji"),
            )
        except ResolutionError:
            # Source unreachable: keep the entry pending for a future retry.
            continue
        except Exception:
            zh = None
        if zh is None and item.get("title_zh"):
            # Miss: keep any previously-derived fallback name rather than blank it.
            item["title_zh_source"] = "synonym_fallback"
        else:
            item["title_zh"] = zh
            item["title_zh_source"] = "wikidata" if zh else "none"
        item["title_zh_attempted"] = True
        item["zh_retries"] = (item.get("zh_retries") or 0) + (0 if zh else 1)
        try:
            db.upsert_anime([item])
        except Exception:
            pass
        with _title_lock:
            _title_state["done"] = idx
            if zh:
                _title_state["hit"] += 1
            else:
                _title_state["miss"] += 1
        time.sleep(0.6)  # be polite to Wikimedia projects

    with _title_lock:
        _title_state["running"] = False
        _title_state["message"] = (
            f"完成：新增 {_title_state['hit']} 部中文名，"
            f"{_title_state['miss']} 部未找到，"
            f"{_title_state['total'] - _title_state['done']} 部因暫時連線問題下次重試"
        )


@app.post("/api/titles/sync")
def start_title_sync(force: bool = False, recheck: bool = False):
    with _title_lock:
        if _title_state["running"]:
            return {"started": False, "status": _title_state}
        _title_state.update(running=True, message="準備中…")
    thread = threading.Thread(target=_title_worker, args=(force, recheck), daemon=True)
    thread.start()
    return {"started": True, "status": _title_state}


@app.get("/api/titles/status")
def title_sync_status():
    return dict(_title_state)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")