from __future__ import annotations

import difflib
import re
import time

import httpx
import zhconv

_WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_ZHWIKI_API = "https://zh.wikipedia.org/w/api.php"
_USER_AGENT = (
    "AniTrack/1.0 (China-title translation bot; "
    "educational local tool)"
)
_TIMEOUT = 12.0
_RETRIES = 4
_RETRY_DELAY = 2.0

_CJK = re.compile(r"[\u4e00-\u9fff]")
_SUBPAGE = ("角色列表", "人物列表", "劇集列表", "配音員", "原聲帶", "各話列表")
# Removes trailing season/movie tokens: "Season 3", "2nd Season", "Part 2", "Movie" etc.
_TAIL = re.compile(
    r"^(.*?)\s+(?:"
    r"S(?:eason)?\s+(?:\d+|[IVX]+)|"
    r"\d+(?:st|nd|rd|th)?\s+Season|"
    r"\d+(?:st|nd|rd|th)?\s*(?:シーズン|期)|"
    r"Movie\s*(?:\([^)]*\))?|"
    r"Film|"
    r"Part\s+(?:\d+|[IVX]+)|"
    r"\d+"
    r")$",
    re.IGNORECASE,
)


class ResolutionError(Exception):
    """Permanent inability to reach the translation sources (retry later)."""


def _norm(s: str) -> str:
    return re.sub(
        r"[\s_\-:：·.,，!！?？'\"（）()【】\[\]~～/]+", "", s or ""
    ).lower()


def _to_traditional(s: str | None) -> str | None:
    if not s:
        return None
    return zhconv.convert(s, "zh-hant")


def _core_keywords(kw: str) -> list[str]:
    """Generate searchable core names from a title (strip season/movie tokens)."""
    kw = (kw or "").strip()
    if not kw:
        return []
    results: list[str] = [kw]
    for sep in (":", "：", " - ", "–"):
        if sep in kw:
            left = kw.split(sep)[0].strip()
            if len(left.split()) >= 2:
                results.append(left)
    cur = kw
    for _ in range(3):
        m = _TAIL.match(cur)
        if not m:
            break
        nxt = m.group(1).strip()
        if not nxt or nxt == cur:
            break
        cur = nxt
        results.append(cur)
    return results


def _get_json(client: httpx.Client, url: str, params: dict) -> dict | None:
    """GET with retries; distinguishes transient failures from success."""
    last: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            resp = client.get(url, params=params)
            if resp.status_code in (429, 500, 502, 503, 504):
                last = httpx.HTTPStatusError(
                    f"status {resp.status_code}", request=resp.request, response=resp
                )
                time.sleep(_RETRY_DELAY * (attempt + 1))
                continue
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
            time.sleep(_RETRY_DELAY * (attempt + 1))
    raise ResolutionError(f"Wikidata/zh-wiki unreachable after retries: {last!r}")


def _wikidata_zh_title(keyword: str) -> str | None:
    """Resolve a Chinese zh-wiki title via Wikidata (batched sitelink lookup)."""
    with httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as c:
        qids: list[str] = []
        seen_qid: set[str] = set()
        seen_kw: set[str] = set()
        for src in _core_keywords(keyword):
            if src.lower() in seen_kw:
                continue
            seen_kw.add(src.lower())
            data = _get_json(
                c,
                _WIKIDATA_API,
                {
                    "action": "wbsearchentities",
                    "format": "json",
                    "language": "en",
                    "type": "item",
                    "limit": "5",
                    "search": src,
                },
            )
            if not data:
                continue
            for hit in data.get("search", []):
                qid = hit.get("id")
                if qid and qid not in seen_qid:
                    seen_qid.add(qid)
                    qids.append(qid)
            if len(qids) >= 25:
                break

        for start in range(0, len(qids), 50):
            batch = qids[start : start + 50]
            data = _get_json(
                c,
                _WIKIDATA_API,
                {
                    "action": "wbgetentities",
                    "format": "json",
                    "ids": "|".join(batch),
                    "props": "sitelinks",
                    "sitefilter": "zhwiki",
                },
            )
            if not data:
                continue
            entities = data.get("entities", {})
            for qid in batch:
                zh = (entities.get(qid, {}).get("sitelinks") or {}).get(
                    "zhwiki", {}
                ).get("title")
                if zh:
                    return zh
    return None


def _zhwiki_search_title(keyword: str) -> str | None:
    """Heuristic zh-wiki search fallback (used when Wikidata has no zh link)."""
    params = {
        "action": "query",
        "list": "search",
        "format": "json",
        "utf8": "1",
        "srsearch": keyword,
        "srlimit": "10",
    }
    with httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}) as c:
        data = _get_json(c, _ZHWIKI_API, params)
        if not data:
            return None
        titles = [x.get("title", "") for x in data.get("query", {}).get("search", [])]
    if not titles:
        return None

    nk = _norm(keyword)
    best: str | None = None
    best_score = 0.0
    for t in titles:
        nt = _norm(t)
        score = difflib.SequenceMatcher(None, nk, nt).ratio()
        if nk and (nk in nt or nt in nk):
            score += 0.4
        if any(b in t for b in _SUBPAGE):
            score -= 0.6
        if score > best_score:
            best_score, best = score, t
    if best is not None and best_score >= 0.5:
        return best
    return None


def resolve_chinese_title(
    native: str | None,
    english: str | None,
    romaji: str | None,
    series_only: bool = True,
) -> str | None:
    """Return a Traditional Chinese title for an anime, or None.

    Priority: Wikidata (english -> romaji), then zh-wiki search (native -> english).
    Raises ResolutionError if the sources are unreachable (transient).
    """
    for kw in (english, romaji):
        if not kw:
            continue
        zh = _wikidata_zh_title(kw)
        if zh:
            return _to_traditional(zh)

    for kw in (native, english, romaji):
        if not kw:
            continue
        zh = _zhwiki_search_title(kw)
        if zh:
            return _to_traditional(zh)
    return None