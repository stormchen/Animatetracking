from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx
import zhconv

from .config import ANILIST_ENDPOINT, ANILIST_USER_AGENT, REQUEST_TIMEOUT

SEASONS = ("WINTER", "SPRING", "SUMMER", "FALL")

_CJK = re.compile(r"[\u4e00-\u9fff]")
# Japanese-only characters: hiragana + katakana (full & half width). A real
# Chinese title contains none of these.
_KANA = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\u30a0-\u30ff\uff65-\uff9f]")

_SEASONAL_QUERY = """
query ($year: Int, $season: MediaSeason, $page: Int, $perPage: Int) {
    Page(page: $page, perPage: $perPage) {
        pageInfo { currentPage hasNextPage lastPage perPage total }
        media(
            type: ANIME
            season: $season
            seasonYear: $year
            sort: [POPULARITY_DESC]
        ) {
            id
            format
            episodes
            duration
            status
            season
            seasonYear
            isAdult
            averageScore
            meanScore
            popularity
            trending
            favourites
            coverImage { extraLarge large large color }
            title { romaji english native }
            genres
            tags { name rank }
            description(asHtml: false)
            siteUrl
            externalLinks { site url type }
studios { nodes { name } }
            nextAiringEpisode { episode airingAt }
            synonyms
            title { romaji english native }
        }
    }
}
"""

_SEARCH_QUERY = """
query ($search: String, $genres: [String], $page: Int, $perPage: Int) {
    Page(page: $page, perPage: $perPage) {
        pageInfo { currentPage hasNextPage perPage total }
        media(
            type: ANIME
            search: $search
            genre_in: $genres
            sort: [POPULARITY_DESC]
        ) {
            id
            format
            episodes
            status
            season
            seasonYear
            isAdult
            averageScore
            meanScore
            popularity
            trending
            favourites
            coverImage { extraLarge large medium color }
            title { romaji english native }
            genres
            tags { name rank }
            description(asHtml: false)
            siteUrl
            externalLinks { site url type }
            synonyms
            title { romaji english native }
        }
    }
}
"""


class AniListError(Exception):
    """Raised when the AniList API returns an error."""


class AniListClient:
    def __init__(self, endpoint: str = ANILIST_ENDPOINT) -> None:
        self.endpoint = endpoint

    def _post(self, query: str, variables: dict) -> dict:
        payload = {"query": query, "variables": variables}
        headers = {
            "User-Agent": ANILIST_USER_AGENT,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
                resp = client.post(self.endpoint, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise AniListError(f"Network error talking to AniList: {exc}") from exc

        if resp.status_code == 429:
            raise AniListError(
                f"Rate limited (429): {resp.text[:300]}"
            )
        if resp.status_code == 404:
            raise AniListError(f"Not found (404): {resp.text[:300]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise AniListError(
                f"Bad JSON from AniList (HTTP {resp.status_code}): {resp.text[:300]}"
            ) from exc

        if resp.status_code != 200 or "data" not in data:
            raise AniListError(f"AniList error: {data}")
        return data["data"]

    @staticmethod
    def _pick_chinese_title(title: dict, synonyms: list[str]) -> str | None:
        """Pick a Chinese title from synonyms/native, converted to Traditional."""
        syn_candidates: list[str] = []
        seen: set[str] = set()
        syns = {s.strip() for s in (synonyms or []) if s and s.strip()}
        for raw in syns:
            # strip trailing parenthetical annotations like " (TV)"
            s = re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()
            if not (1 <= len(s) <= 60):
                continue
            if not (_CJK.search(s) and not _KANA.search(s)):
                continue
            if s in seen:
                continue
            seen.add(s)
            syn_candidates.append(s)

        native = (title or {}).get("native") or ""
        native_ok = (
            2 <= len(native) <= 60
            and _CJK.search(native)
            and not _KANA.search(native)
        )

        if syn_candidates:
            best = max(syn_candidates, key=len)
        elif native_ok:
            best = native
        else:
            return None
        return zhconv.convert(best, "zh-hant")

    @staticmethod
    def _pick_youtube(external_links: list) -> list[dict]:
        """Keep YouTube external links (channel/playlist URLs), deduplicated."""
        out: list[dict] = []
        seen: set[str] = set()
        for ln in external_links or []:
            if not isinstance(ln, dict):
                continue
            url = (ln.get("url") or "").strip()
            if not url or url in seen:
                continue
            site = (ln.get("site") or "").lower()
            url_l = url.lower()
            if "youtube" in site or "youtu.be" in url_l or "youtube.com" in url_l:
                seen.add(url)
                out.append({"url": url, "type": ln.get("type")})
        return out

    @staticmethod
    def _normalize_media(m: dict) -> dict:
        """Flatten the AniList media object into a simple dict for storage."""
        title = m.get("title") or {}
        cover = m.get("coverImage") or {}
        tags = [(t.get("name") or "") for t in (m.get("tags") or []) if t]
        studios = [
            s.get("name")
            for s in (m.get("studios") or {}).get("nodes") or []
            if s.get("name")
        ]
        return {
            "id": m["id"],
            "format": m.get("format"),
            "episodes": m.get("episodes"),
            "duration": m.get("duration"),
            "status": m.get("status"),
            "season": m.get("season"),
            "season_year": m.get("seasonYear"),
            "is_adult": bool(m.get("isAdult")),
            "average_score": m.get("averageScore"),
            "mean_score": m.get("meanScore"),
            "popularity": m.get("popularity") or 0,
            "trending": m.get("trending") or 0,
            "favourites": m.get("favourites") or 0,
            "cover_large": cover.get("extraLarge") or cover.get("large"),
            "cover_medium": cover.get("medium"),
            "cover_color": cover.get("color"),
            "title_romaji": title.get("romaji"),
            "title_english": title.get("english"),
            "title_native": title.get("native"),
            "title_zh": AniListClient._pick_chinese_title(title, m.get("synonyms") or []),
            "genres": m.get("genres") or [],
            "tags": tags,
            "synopsis": m.get("description"),
            "site_url": m.get("siteUrl"),
            "youtube": AniListClient._pick_youtube(m.get("externalLinks") or []),
            "studios": studios,
            "next_episode_number": (
                (m.get("nextAiringEpisode") or {}).get("episode")
            ),
            "next_airing_at": (
                (m.get("nextAiringEpisode") or {}).get("airingAt")
            ),
        }

    def fetch_seasonal(
        self, year: int, season: str, page: int = 1, per_page: int = 50
    ) -> tuple[list[dict], bool]:
        """Fetch one page of seasonal anime. Returns (media, has_next_page)."""
        if season.upper() not in SEASONS:
            raise AniListError(f"Invalid season: {season}")
        data = self._post(
            _SEASONAL_QUERY,
            {
                "year": int(year),
                "season": season.upper(),
                "page": int(page),
                "perPage": int(per_page),
            },
        )
        page_data = data.get("Page", {})
        media = [
            self._normalize_media(m) for m in page_data.get("media", []) or []
        ]
        page_info = page_data.get("pageInfo", {}) or {}
        return media, bool(page_info.get("hasNextPage"))

    def fetch_all_seasonal(self, year: int, season: str) -> list[dict]:
        """Fetch every anime for a season (walk all pages)."""
        results: list[dict] = []
        page = 1
        while True:
            media, has_next = self.fetch_seasonal(year, season, page=page)
            results.extend(media)
            if not has_next:
                break
            page += 1
        return results

    def search(
        self,
        search: str | None = None,
        genres: list[str] | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[dict], int]:
        """Search anime by keyword and/or genres. Returns (media, total)."""
        variables: dict = {"page": int(page), "perPage": int(per_page)}
        if search:
            variables["search"] = search.strip()
        if genres:
            variables["genres"] = [g.strip() for g in genres if g.strip()]
        data = self._post(_SEARCH_QUERY, variables)
        page_data = data.get("Page", {})
        media = [
            self._normalize_media(m) for m in page_data.get("media", []) or []
        ]
        total = (page_data.get("pageInfo") or {}).get("total") or 0
        return media, total


def current_season() -> tuple[int, str]:
    """Return (year, season) for the current month, suitable for AniList."""
    now = datetime.now(timezone.utc)
    month = now.month
    year = now.year
    if 3 <= month <= 5:
        season = "SPRING"
    elif 6 <= month <= 8:
        season = "SUMMER"
    elif 9 <= month <= 11:
        season = "FALL"
    else:
        season = "WINTER"
    return year, season


def previous_season(year: int, season: str) -> tuple[int, str]:
    idx = SEASONS.index(season.upper())
    if idx == 0:
        return year - 1, SEASONS[-1]
    return year, SEASONS[idx - 1]