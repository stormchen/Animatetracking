import app.wikimedia as wm
from app.wikimedia import resolve_chinese_title


def test_prefers_wikidata_and_converts_simplified(monkeypatch):
    monkeypatch.setattr(
        wm, "_wikidata_zh_title", lambda kw: "无职转生～到了异世界就拿出真本事～"
    )
    zh = resolve_chinese_title("無職転生", "Mushoku Tensei", "Mushoku Tensei")
    assert zh == "無職轉生～到了異世界就拿出真本事～"


def test_zhwiki_fallback_used_when_wikidata_empty(monkeypatch):
    monkeypatch.setattr(wm, "_wikidata_zh_title", lambda kw: None)
    monkeypatch.setattr(wm, "_zhwiki_search_title", lambda kw: "我独自升级 (动画)")
    zh = resolve_chinese_title(None, "Solo Leveling", "Solo Leveling")
    assert zh == "我獨自升級 (動畫)"


def test_returns_none_when_both_fail(monkeypatch):
    monkeypatch.setattr(wm, "_wikidata_zh_title", lambda kw: None)
    monkeypatch.setattr(wm, "_zhwiki_search_title", lambda kw: None)
    assert resolve_chinese_title(None, "Nothing Here", "Nothing Here") is None