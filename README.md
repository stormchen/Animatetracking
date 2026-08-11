# AniTrack · 動漫追蹤與新番排行

追蹤每個月評價最好的新番（新番排行 Top10）、記錄你看過的動畫、並可用關鍵字/類型搜尋（例如「異世界」）。

資料來源：**AniList GraphQL API**（免費、無需金鑰），前端會快取到本機 SQLite。

## 功能

- **本月 Top10**：當季新番按「社群評分 × 人氣加權」排名
- **新番季列表**：依 → 季（WINTER/SPRING/SUMMER/FALL）+ 年份載入全部新番
- **搜尋**：關鍵字 + 類型（可多選）+ 最低評分 + 排序（人氣/評分/熱度/收藏/名稱/集數）
- **觀看清單**：想看 / 在看 / 已看完 / 棄追，記錄看至第幾集、個人評分（0-10）、備註
- **偏好設定**：儲存偏好的類型與關鍵字，一鍵「推薦」符合條件的作品

## 安裝與執行

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

開啟 <http://127.0.0.1:8000>。

> 首次載入某季時需從 AniList 抓取，約 10–30 秒；之後 6 小時內直接使用本機快取。

## API 簡介

| 方法 | 路徑 | 說明 |
|---|---|---|
| GET | `/api/season?year=&season=&force=` | 某季新番（自動抓取 + 快取） |
| GET | `/api/top10?year=&season=` | 當季 Top10 排行 |
| GET | `/api/search?q=&genres=&min_score=&sort_by=` | 搜尋本機快取 |
| GET | `/api/anime/{id}` | 單部詳細資料（含我的紀錄） |
| PUT/DELETE | `/api/anime/{id}/watch` | 新增/更新/刪除觀看紀錄 |
| GET | `/api/watchlist?status=` | 我的觀看清單 |
| GET | `/api/genres` | 以取得之類型清單 |
| GET/POST/DELETE | `/api/preferences` | 偏好類型/關鍵字 |
| GET | `/api/search/preferences` | 依偏好推薦 |

## 測試

```bash
.venv\Scripts\python -m pytest tests -v
```

測試使用獨立的測試資料庫（`ANITRACK_DB` 環境變數），不影響正式資料。

## 專案結構

```
app/
  main.py        # FastAPI 應用與路由
  anilist.py     # AniList GraphQL Client
  database.py    # SQLite 資料層
  config.py      # 設定（DB 路徑可用 ANITRACK_DB 覆寫）
static/          # 前端（index.html / style.css / app.js）
tests/           # pytest 測試
anitrack.db      # 執行時自動產生的 SQLite 資料庫
```