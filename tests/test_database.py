import pytest

from app.anilist import AniListClient, AniListError, current_season
from app.database import Database

from .conftest import make


class TestCurrentSeason:
    def test_returns_valid_range(self):
        year, season = current_season()
        assert year >= 1990
        assert season in ("WINTER", "SPRING", "SUMMER", "FALL")


class TestAniListClientErrorHandling:
    def test_unreachable_endpoint_raises(self):
        client = AniListClient(endpoint="http://127.0.0.1:1/not-reachable")
        with pytest.raises(AniListError):
            client.fetch_seasonal(2026, "WINTER", page=1, per_page=5)

    def test_invalid_season_raises(self):
        client = AniListClient()
        with pytest.raises(AniListError):
            client.fetch_seasonal(2026, "NOTASEASON", page=1, per_page=5)


class TestChineseTitle:
    def test_pick_from_simplified_synonyms(self):
        client = AniListClient()
        zh = client._pick_chinese_title(
            {"romaji": "Sword Art Online", "native": "ソードアート・オンライン"},
            ["刀剑神域 (TV)", "SAO", "ソードアート・オンライン"],
        )
        assert zh == "刀劍神域"

    def test_no_chinese_returns_none(self):
        client = AniListClient()
        zh = client._pick_chinese_title(
            {"romaji": "Frieren", "native": "フリーレン"},
            ["Frieren at the Funeral"],
        )
        assert zh is None

    def test_native_chinese_fallback(self):
        client = AniListClient()
        zh = client._pick_chinese_title(
            {"romaji": "Tian Guan Ci Fu", "native": "天官赐福"},
            [],
        )
        assert zh == "天官賜福"


class TestDatabase:
    def setup_method(self):
        self.db = Database()

    def test_upsert_and_get(self):
        self.db.upsert_anime([make(7, title_romaji="Log Horizon")])
        got = self.db.get_anime(7)
        assert got["title_romaji"] == "Log Horizon"
        assert got["genres"] == ["Action", "Adventure", "Fantasy"]
        assert "title_zh" in got

    def test_season_freshness(self):
        assert not self.db.is_season_fresh(2026, "WINTER")
        self.db.mark_season_fetched(2026, "WINTER")
        assert self.db.is_season_fresh(2026, "WINTER")
        with self.db._conn() as conn:
            conn.execute(
                "UPDATE season_cache SET fetched_at = ?",
                (self.db.now_ts() - 10_000_000,),
            )
        assert not self.db.is_season_fresh(2026, "WINTER")

    def test_query_anime_filters_and_sort(self):
        self.db.upsert_anime([
            make(1, title_romaji="Sword Art Online", genres=["Action"], mean_score=80),
            make(2, title_romaji="Frieren", genres=["Adventure"], mean_score=90),
            make(3, title_romaji="Classroom", genres=["Slice of Life"], mean_score=70),
        ])

        items, total = self.db.query_anime(genres=["Action"])
        assert total == 1 and items[0]["id"] == 1

        items, total = self.db.query_anime(search="online")
        assert total == 1 and items[0]["id"] == 1

        items, total = self.db.query_anime(search="不存在的關鍵字")
        assert total == 0

        items, total = self.db.query_anime(min_score=75)
        assert {i["id"] for i in items} == {1, 2}

        items, total = self.db.query_anime(sort_by="score")
        assert items[0]["id"] == 2 and items[-1]["id"] == 3

        items, total = self.db.query_anime(season="WINTER", year=2026)
        assert total == 3

    def test_upsert_preserves_wikidata_title_over_normalize(self):
        # First: wikidata title stored.
        self.db.upsert_anime([make(31, title_zh="無職轉生～到了異世界就拿出真本事～", title_zh_source="wikidata", title_zh_attempted=True)])
        # Then a season re-normalize gives a synonym-derived (weaker) title.
        self.db.upsert_anime([make(31, title_zh="無職転生 第3期", title_zh_source=None)])
        got = self.db.get_anime(31)
        assert got["title_zh"] == "無職轉生～到了異世界就拿出真本事～"
        assert got["title_zh_source"] == "wikidata"
        assert got["title_zh_attempted"] is True

    def test_upsert_new_item_keeps_incoming_zh(self):
        self.db.upsert_anime([make(32, title_zh="幼女戰記", title_zh_source="wikidata")])
        got = self.db.get_anime(32)
        assert got["title_zh"] == "幼女戰記"

    def test_search_matches_chinese_synopsis(self):
        self.db.upsert_anime([
            make(5, synopsis_zh="少年進入異世界冒險的故事"),
            make(6, synopsis_zh="魔法少女日常"),
        ])
        items, total = self.db.query_anime(search="異世界")
        assert total == 1 and items[0]["id"] == 5

    def test_upsert_preserves_synopsis_zh_over_normalize(self):
        self.db.upsert_anime([make(41, synopsis_zh="少年被困於遊戲世界。", synopsis_zh_source="zhwiki")])
        self.db.upsert_anime([make(41)])  # season re-normalize: no synopsis_zh
        got = self.db.get_anime(41)
        assert got["synopsis_zh"] == "少年被困於遊戲世界。"
        assert got["synopsis_zh_source"] == "zhwiki"
        assert got["synopsis"] == "A boy gets trapped in a game world."

    def test_watch_record_lifecycle(self):
        self.db.upsert_anime([make(5)])
        self.db.set_watch_record(5, status="watching", progress=4, personal_score=8)
        rec = self.db.get_watch_record(5)
        assert rec["status"] == "watching" and rec["progress"] == 4

        self.db.set_watch_record(5, status="completed")
        rec = self.db.get_watch_record(5)
        assert rec["status"] == "completed" and rec["progress"] == 4

        assert self.db.delete_watch_record(5)
        assert self.db.get_watch_record(5) is None

    def test_watch_record_validation(self):
        self.db.upsert_anime([make(6)])
        with pytest.raises(ValueError):
            self.db.set_watch_record(6, status="nope")
        with pytest.raises(ValueError):
            self.db.set_watch_record(6, personal_score=11)
        with pytest.raises(ValueError):
            self.db.set_watch_record(6, personal_score=-1)

    def test_preferences(self):
        self.db.add_preference("genre", "Isekai")
        self.db.add_preference("keyword", "冒險")
        self.db.add_preference("genre", "Isekai")  # duplicate ignored
        prefs = self.db.get_preferences()
        assert prefs["genre"] == ["Isekai"]
        assert prefs["keyword"] == ["冒險"]

        self.db.remove_preference("genre", "Isekai")
        assert self.db.get_preferences()["genre"] == []

        with pytest.raises(ValueError):
            self.db.add_preference("bogus", "x")

    def test_watchlist_join(self):
        self.db.upsert_anime([make(9), make(10)])
        self.db.set_watch_record(9, status="completed")
        self.db.set_watch_record(10, status="watching")

        rows = self.db.get_watchlist(status="completed")
        assert len(rows) == 1 and rows[0]["anime"]["id"] == 9
        assert len(self.db.get_watchlist()) == 2