import app.wikimedia as wm
from app.wikimedia import resolve_chinese_entry, resolve_chinese_title


def _no_extract(*a, **k):
    return None


def test_prefers_wikidata_and_converts_simplified(monkeypatch):
    monkeypatch.setattr(
        wm, "_wikidata_zh_title", lambda kw: "无职转生～到了异世界就拿出真本事～"
    )
    monkeypatch.setattr(wm, "_zhwiki_extract", _no_extract)
    zh = resolve_chinese_title("無職転生", "Mushoku Tensei", "Mushoku Tensei")
    assert zh == "無職轉生～到了異世界就拿出真本事～"


def test_zhwiki_fallback_used_when_wikidata_empty(monkeypatch):
    monkeypatch.setattr(wm, "_wikidata_zh_title", lambda kw: None)
    monkeypatch.setattr(wm, "_zhwiki_search_title", lambda kw: "我独自升级 (动画)")
    monkeypatch.setattr(wm, "_zhwiki_extract", _no_extract)
    zh = resolve_chinese_title(None, "Solo Leveling", "Solo Leveling")
    assert zh == "我獨自升級 (動畫)"


def test_returns_none_when_both_fail(monkeypatch):
    monkeypatch.setattr(wm, "_wikidata_zh_title", lambda kw: None)
    monkeypatch.setattr(wm, "_zhwiki_search_title", lambda kw: None)
    assert resolve_chinese_title(None, "Nothing Here", "Nothing Here") is None


def test_entry_has_title_and_synopsis(monkeypatch):
    monkeypatch.setattr(
        wm, "_wikidata_zh_title", lambda kw: "无职转生"
    )
    monkeypatch.setattr(
        wm, "_zhwiki_extract",
        lambda t: "无职转生～到了异世界就拿出真本事～是一部日本动画。" if t == "无职转生" else None,
    )
    entry = resolve_chinese_entry("無職転生", "Mushoku Tensei", "Mushoku Tensei")
    assert entry["title"] == "無職轉生"
    assert entry["source"] == "wikidata"
    assert "日本動畫" in entry["synopsis"]


def test_entry_missing_synopsis_when_wiki_no_intro(monkeypatch):
    monkeypatch.setattr(wm, "_wikidata_zh_title", lambda kw: "某作品")
    monkeypatch.setattr(wm, "_zhwiki_extract", lambda t: None)
    entry = resolve_chinese_entry(None, "SomeTitle", "SomeTitle")
    assert entry["title"] == "某作品"
    assert entry["synopsis"] is None
    assert entry["source"] == "wikidata"


def test_entry_all_none(monkeypatch):
    monkeypatch.setattr(wm, "_wikidata_zh_title", lambda kw: None)
    monkeypatch.setattr(wm, "_zhwiki_search_title", lambda kw: None)
    entry = resolve_chinese_entry(None, "Nothing", "Nothing")
    assert entry == {"title": None, "synopsis": None, "source": None}
