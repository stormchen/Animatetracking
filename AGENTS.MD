# AGENTS.md

本檔協助 OpenCode / 其他 agent 在本 repo 快速上手、避免踩坑。

## 強制規範

- **語言**:所有回覆、思考過程、任務清單一律使用中文。固定指令:「Implementation Plan, Task List and Thought in Chinese」。
- **產生物**:除非另有要求,生成的應用/介面/文案一律用**繁體中文**(zh-hant)。
- **終端**:Windows + PowerShell 7。**禁止 Linux 指令**(如 `ls`、`cat`、`&&` 以外的 sh 語法);路徑用反引號封裝含空格者。

## 專案速寫

動漫追蹤 app:抓當季新番 Top10、記錄觀看重複、關鍵字/類型搜尋,並解析中文名與中文劇情。

- **框架**:FastAPI 後端 + SQLite 資料層 + 原生 JS 前端(`static/`,無建置步驟、無 npm 套件)。
- **入口**:`app/main.py` 的 `app`(FastAPI)與 `db`(Database);啟動服務在 `app/main.py`,`app.database` 為唯一資料存取層。

## 指令(唯一可執行來源,已驗證)

```powershell
# 環境
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 啟動
.venv\Scripts\python -m uvicorn app.main:app --port 8000   # http://127.0.0.1:8000

# 測試(全部)
.venv\Scripts\python -m pytest tests -v

# 單一測試檔 / 單一測試
.venv\Scripts\python -m pytest tests\test_api.py -v
.venv\Scripts\python -m pytest "tests\test_api.py::TestSeasonAndTop10::test_top10_orders_by_score" -v
```

> **沒有 lint / typecheck / CI / pre-commit / 建置步驟** — 唯一品質門是 `pytest`。改動後務必跑 `pytest tests` 驗證。

## 外部依賴與快取

- **AniList GraphQL**(`app/anilist.py`):抓季列表/搜尋,免費、無需金鑰。快取 TTL = **6 小時**(`config.CACHE_TTL_HOURS`);首次載入某季會走全部頁,約 10–30 秒。
- **Wikimedia**(`app/wikimedia.py`,Wikidata + 中文維基):解析中文名與中文劇情,屬**背景執行緒**`POST /api/titles/sync`;每部間隔 **0.6s** 禮貌限速,**失敗會自動重試上限 3 次**(`zh_retries`),連線失敗(`ResolutionError`)留待下次。

## 環境變數

- `ANITRACK_DB`:覆寫 SQLite 路徑(預設 `anitrack.db`)。測試以 `tests/conftest.py` 設成臨時目錄,**不影響正式資料**;測試使用 mock,不需真實網路。

## 易踩的坑

- **繁簡轉換**:所有中文標題/劇情一律經 `zhconv.convert(..., "zh-hant")` 轉**繁體**(見 `anilist.py`、`wikimedia.py`)。新增中文邏輯請沿用,勿輸出簡體。
- **中文標題來源**:`_pick_chinese_title` 從 synonyms/native 挑「含 CJK、無假名」者;`title_zh` 為 `null` 表示尚未解析,非資料缺失。
- **Top10 排序**是用 `mean_score × (1 + popularity/100000)` 自訂加權,並**排除 `is_adult`**(見 `main.py`)/非 AniList `POPULARITY` 直出。
- **路由順序**:FastAPI 依註冊順序匹配。`/api/anime/{anime_id}` 用 `int` 參數,故 `/api/search/preferences` 等字串路由不受影響;但若新增**字串**參數路由(如 `/api/anime/{name}`),須排在具體字串端點之後。
- **調試殘檔**:repo 根目錄大量 `dbg_*.txt`、`verify_*.txt`、`wiki_*.txt`、`bgm_*.txt`、`zh_result.txt`、`*.log`(如 `server.err.log`)與 `dbg.py` 是**手動調試產物,非正式程式與測試**,勿修改/依賴。
- **DB 結構**由 `app/database.py` 的 `init_db()` 管理,表:`anime_cache`、`season_cache`、`watch_records`、`preferences`、`search_log`。改 schema 時 `conftest.clean_db` 會清這五張表,新增表也要一併納入。

## 專案結構

```
app/main.py      # FastAPI 應用、路由、背景同步執行緒
app/anilist.py   # AniList GraphQL Client + 中文標題/繁簡轉換
app/wikimedia.py # Wikidata/中文維基 解析中文名與劇情
app/database.py  # SQLite 資料層(upsert / query / 紀錄 / 偏好)
app/config.py    # 設定(DB 路徑、快取 TTL、端點)
static/          # 前端:index.html / style.css / app.js(原生 JS)
tests/           # pytest:conftest.py + test_api/test_database/test_wikimedia
```
