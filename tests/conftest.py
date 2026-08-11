import os
import tempfile
from pathlib import Path

import pytest

# Point the app at an isolated test database before importing the app.
_tmp = tempfile.mkdtemp(prefix="anitrack_test_")
os.environ["ANITRACK_DB"] = str(Path(_tmp) / "test.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app, db  # noqa: E402
from app.database import init_db  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_db():
    """Ensure schema exists, then wipe tables between tests for isolation."""
    init_db()
    conn = db._conn()
    for table in (
        "watch_records",
        "preferences",
        "search_log",
        "anime_cache",
        "season_cache",
    ):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()
    yield


DTO = {
    "id": 100,
    "format": "TV",
    "episodes": 12,
    "duration": 24,
    "status": "RELEASING",
    "season": "WINTER",
    "season_year": 2026,
    "is_adult": False,
    "average_score": 80,
    "mean_score": 82,
    "popularity": 50000,
    "trending": 1000,
    "favourites": 300,
    "cover_large": "https://example.com/large.jpg",
    "cover_medium": "https://example.com/med.jpg",
    "cover_color": "#ab1234",
    "title_romaji": "Sword Art Online",
    "title_english": "Sword Art Online",
    "title_native": "ソードアート・オンライン",
    "genres": ["Action", "Adventure", "Fantasy"],
    "tags": ["Isekai", "Game", "Magic"],
    "synopsis": "A boy gets trapped in a game world.",
    "site_url": "https://anilist.co/anime/1",
    "studios": ["A-1 Pictures"],
    "next_episode_number": 13,
    "next_airing_at": 9999999999,
}


def make(anime_id, **over):
    d = dict(DTO)
    d["id"] = anime_id
    d.update(over)
    if "title_english" not in over:
        d["title_english"] = None
    if "title_native" not in over:
        d["title_native"] = None
    if "title_zh" not in over:
        d["title_zh"] = None
    return d