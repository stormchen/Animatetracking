from fastapi.testclient import TestClient

from .conftest import make


def test_index(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    assert "AniTrack" in r.text


class TestSeasonAndTop10:
    def _seed(self):
        from app.main import db

        db.upsert_anime([
            make(1, title_romaji="Frieren", mean_score=90, popularity=999999),
            make(2, title_romaji="Sword Story", mean_score=60, popularity=5),
        ])
        db.mark_season_fetched(2026, "WINTER")

    def test_season_requires_valid_season(self, client):
        r = client.get("/api/season", params={"season": "BOGUS"})
        assert r.status_code == 400

    def test_season_returns_seed_data(self, client):
        self._seed()
        from app.main import db

        db.mark_season_fetched(2026, "WINTER")
        r = client.get("/api/season", params={"year": 2026, "season": "WINTER"})
        assert r.status_code == 200
        body = r.json()
        assert body["season"] == "WINTER"
        assert body["total"] == 2

    def test_top10_orders_by_score(self, client):
        self._seed()
        from app.main import db

        db.mark_season_fetched(2026, "WINTER")
        r = client.get("/api/top10", params={"year": 2026, "season": "WINTER"})
        assert r.status_code == 200
        ranked = r.json()["ranked"]
        assert ranked[0]["rank"] == 1
        assert ranked[0]["media"]["id"] == 1  # Frieren (highest score)


class TestSearch:
    def test_search_empty_cache_returns_hint(self, client):
        r = client.get("/api/search", params={"q": "異世界"})
        assert r.status_code == 200
        assert r.json()["hint"]

    def test_search_cached(self, client):
        from app.main import db

        db.upsert_anime([
            make(1, title_romaji="Re:Zero", genres=["Action", "Fantasy"]),
            make(2, title_romaji="Other", genres=["Romance"]),
        ])
        r = client.get("/api/search", params={"q": "re:zero"})
        assert r.json()["total"] == 1

        r = client.get("/api/search", params={"genres": ["Romance"]})
        assert r.json()["total"] == 1 and r.json()["items"][0]["id"] == 2


class TestWatchCRUD:
    def seed(self, client):
        from app.main import db

        db.upsert_anime([make(50)])

    def test_put_get_watch(self, client):
        self.seed(client)
        r = client.put(
            "/api/anime/50/watch",
            json={"status": "watching", "progress": 3, "personal_score": 9},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "watching" and body["progress"] == 3

        r = client.get("/api/anime/50")
        assert r.json()["my_score"] == 9

    def test_watch_unknown_anime_404(self, client):
        r = client.put("/api/anime/999999/watch", json={"status": "completed"})
        assert r.status_code == 404

    def test_invalid_score_400(self, client):
        self.seed(client)
        r = client.put("/api/anime/50/watch", json={"personal_score": 99})
        assert r.status_code == 422  # rejected by pydantic range (0-10)

    def test_delete_watch(self, client):
        self.seed(client)
        client.put("/api/anime/50/watch", json={"status": "watching"})
        r = client.delete("/api/anime/50/watch")
        assert r.status_code == 200
        assert client.get("/api/watchlist").json() == []


class TestPreferences:
    def test_sync_title_status_and_start(self, client, monkeypatch):
        from app import main as m

        monkeypatch.setattr(m, "_title_worker", lambda: None)
        r = client.post("/api/titles/sync")
        assert r.status_code == 200
        assert r.json()["started"] is True
        r = client.get("/api/titles/status")
        assert "running" in r.json()
        with m._title_lock:
            m._title_state["running"] = False

    def test_crud(self, client):
        r = client.post("/api/preferences", json={"kind": "genre", "value": "异世界"})
        assert r.status_code == 200
        assert r.json()["preferences"]["genre"] == ["异世界"]

        r = client.get("/api/preferences")
        assert r.json()["preferences"]["genre"] == ["异世界"]

        r = client.delete("/api/preferences", params={"kind": "genre", "value": "异世界"})
        assert r.json()["preferences"]["genre"] == []

    def test_recommend_uses_prefs(self, client):
        from app.main import db

        db.upsert_anime([
            make(1, title_romaji="Isekai Wars", genres=["Fantasy"], tags=["Isekai"]),
            make(2, title_romaji="Slice Life", genres=["Slice of Life"]),
        ])
        client.post("/api/preferences", json={"kind": "genre", "value": "Fantasy"})
        client.post("/api/preferences", json={"kind": "keyword", "value": "isekai"})
        r = client.get("/api/search/preferences")
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == 1