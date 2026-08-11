import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = Path(os.environ.get("ANITRACK_DB", str(BASE_DIR / "anitrack.db")))

ANILIST_ENDPOINT = "https://graphql.anilist.co"
ANILIST_USER_AGENT = "AniTrack/1.0"
REQUEST_TIMEOUT = 30
# How fresh (in hours) cached season data must be before refetching from AniList
CACHE_TTL_HOURS = 6