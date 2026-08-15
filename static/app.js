"use strict";

const SEASONS = ["WINTER", "SPRING", "SUMMER", "FALL"];

async function api(url, opts = {}) {
    const res = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...opts,
    });
    const text = await res.text();
    let data = {};
    try { data = text ? JSON.parse(text) : {}; } catch (e) { data = { raw: text }; }
    if (!res.ok) {
        const msg = data.detail || data.message || `HTTP ${res.status}`;
        throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
    }
    return data;
}

function esc(s) {
    if (s == null) return "";
    return String(s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function titleOf(m) {
    return m.title_zh || m.title_romaji || m.title_english || m.title_native || `#${m.id}`;
}

function genreTags(m) {
    return (m.genres || []).slice(0, 4).map(g => `<span class="tag">${esc(g)}</span>`).join("");
}
const statusTags = genreTags;

function statusChip(m) {
    if (!m.watch_status) return "";
    const labels = { want_to_watch: "想看", watching: "在看", completed: "已看完", dropped: "棄追" };
    return `<span class="watch-chip ${esc(m.watch_status)}">${esc(labels[m.watch_status] || m.watch_status)}</span>`;
}

function mediaName(m) { return titleOf(m); }

function cardHTML(m, rank) {
    const cover = m.cover_large || m.cover_medium || "";
    const badge = rank
        ? `<div class="rank-badge ${rank === 1 ? "n1" : ""}">${rank}</div>`
        : "";
    return `
    <div class="card" data-id="${m.id}" data-cover="${esc(cover)}" onclick="openDetail(${m.id})">
        ${badge}
        ${cover ? `<img class="cover" src="${esc(cover)}" alt="" loading="lazy">` : '<div class="cover"></div>'}
        <div class="card-info">
            <h3>${esc(titleOf(m))}${statusChip(m)}</h3>
            <div class="meta">⭐ ${m.mean_score ?? "?"} · ♥ ${m.popularity ?? 0} · 📺 ${m.episodes ?? "?"}話</div>
            <div class="tags">${statusTags(m)}${(m.tags || []).slice(0, 3).map(t => `<span class="tag">${esc(t)}</span>`).join("")}</div>
        </div>
    </div>`;
}

function rowHTML(rec) {
    const m = rec.anime;
    if (!m || !m.id) return "";
    const map = { want_to_watch: "想看", watching: "在看", completed: "已看完", dropped: "棄追" };
    const cover = m.cover_large || m.cover_medium || "";
    const score = rec.personal_score != null ? rec.personal_score : "—";
    return `
    <div class="row" data-id="${m.id}">
        ${cover ? `<img class="cover" src="${esc(cover)}" alt="" loading="lazy" onclick="openDetail(${m.id})">` : '<div class="cover"></div>'}
        <div class="info">
            <div class="t">${esc(titleOf(m))}</div>
            <div class="s">${esc(m.season || "?")} ${esc(m.season_year || "")} · 個人評分 ${esc(score)} / 10</div>
        </div>
        <select class="wr-status" onchange="updateWatch(${m.id}, {status:this.value})">
            ${Object.keys(map).map(k => `<option value="${k}" ${rec.status === k ? "selected" : ""}>${map[k]}</option>`).join("")}
        </select>
        <input class="wr-progress" type="number" min="0" value="${esc(rec.progress)}" style="width:70px"
            onchange="updateWatch(${m.id}, {progress:Number(this.value)})" title="觀看進度">
        <button class="btn" onclick="openDetail(${m.id})">詳情</button>
        <button class="btn" style="background:#ef4444;color:#fff" onclick="deleteWatch(${m.id})">刪除</button>
    </div>`;
}

function setStatus(el, text, isError = false) {
    if (!el) return;
    el.textContent = text || "";
    el.className = "status" + (isError ? " error" : "");
}

async function loadTop() {
    const el = document.getElementById("home-status");
    setStatus(el, "載入中...");
    const year = Number(document.getElementById("home-year").value) || new Date().getFullYear();
    const season = document.getElementById("home-season").value;
    const force = el.dataset.force === "1";
    try {
        const data = await api(`/api/top10?year=${year}&season=${season}&force=${force}`);
        document.getElementById("home-list").innerHTML = data.ranked.map((r) =>
            cardHTML(r.media, r.rank, false)
        ).join("");
        setStatus(el, `${data.count} 部 · ${data.season} ${data.year}`);
        el.dataset.force = "0";
    } catch (e) {
        setStatus(el, "失敗：" + e.message, true);
    }
}

async function loadSeason() {
    const el = document.getElementById("season-status");
    setStatus(el, "載入中（首次需從 AniList 抓取，可能需 1 分鐘）...");
    const year = Number(document.getElementById("season-year").value) || new Date().getFullYear();
    const season = document.getElementById("season-pick").value;
    const force = el.dataset.force === "1";
    try {
        const data = await api(`/api/season?year=${year}&season=${season}&force=${force}&limit=500`);
        document.getElementById("season-grid").innerHTML = data.items.map((m) => cardHTML(m)).join("");
        setStatus(el, `共 ${data.total} 部新番`);
        el.dataset.force = "0";
    } catch (e) {
        setStatus(el, "錯誤：" + e.message, true);
    }
}

async function doSearch() {
    const el = document.getElementById("search-status");
    setStatus(el, "搜尋中...");
    const q = document.getElementById("search-q").value.trim();
    const genres = Array.from(document.getElementById("search-genre").selectedOptions).map(o => o.value);
    const min = document.getElementById("search-min").value;
    const sort = document.getElementById("search-sort").value;
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    genres.forEach(g => params.append("genres", g));
    if (min) params.set("min_score", min);
    params.set("sort_by", sort);
    try {
        const data = await api(`/api/search?${params.toString()}`);
        if (data.hint) { setStatus(el, data.hint, true); }
        document.getElementById("search-grid").innerHTML = data.items.map((m) => cardHTML(m)).join("");
        setStatus(el, `找到 ${data.total} 筆`);
    } catch (e) {
        setStatus(el, "錯誤：" + e.message, true);
    }
}

async function loadGenres() {
    try {
        const data = await api("/api/genres");
        const sel = document.getElementById("search-genre");
        sel.innerHTML = `<option value="">-- 選擇類型 (可多選) --</option>` +
            data.genres.map(g => `<option value="${esc(g)}">${esc(g)}</option>`).join("");
    } catch (e) { /* backend may not have data yet */ }
}

async function loadWatchlist() {
    const el = document.getElementById("watch-status-msg");
    const status = document.getElementById("watch-status").value;
    try {
        const rows = await api(`/api/watchlist${status ? `?status=${status}` : ""}`);
        document.getElementById("watch-list").innerHTML = rows.map(rowHTML).join("") ||
            '<div class="meta" style="padding:12px">清單是空的。</div>';
        setStatus(el, `${rows.length} 筆紀錄`);
    } catch (e) {
        setStatus(el, "錯誤：" + e.message, true);
    }
}

async function updateWatch(id, patch) {
    try {
        await api(`/api/anime/${id}/watch`, {
            method: "PUT",
            body: JSON.stringify(patch),
        });
        loadWatchlist();
    } catch (e) { alert("更新失敗：" + e.message); }
}

async function updateWatchStatus(id, status) {
    await updateWatch(id, { status });
}

async function deleteWatch(id) {
    if (!confirm("確定從清單刪除？")) return;
    try {
        await api(`/api/anime/${id}/watch`, { method: "DELETE" });
        loadWatchlist();
    } catch (e) { alert("刪除失敗：" + e.message); }
}

async function loadPrefs() {
    const data = await api("/api/preferences");
    renderPrefs(data.preferences);
}
function renderPrefs(prefs) {
    const box = document.getElementById("pref-list");
    const kinds = { genre: "類型", keyword: "關鍵字" };
    box.innerHTML = Object.entries(prefs).map(([kind, list]) =>
        list.map(v =>
            `<span class="pref-pill">${esc(kinds[kind] || kind)}: ${esc(v)} <button onclick="removePref('${kind}','${esc(v)}')">✕</button></span>`
        ).join("")
    ).join("") || `<span class="status">尚未設定任何偏好。</span>`;
}
async function removePref(kind, value) {
    await api(`/api/preferences?kind=${encodeURIComponent(kind)}&value=${encodeURIComponent(value)}`, { method: "DELETE" });
    await loadPrefs();
}
async function addPref() {
    const kind = document.getElementById("pref-kind").value;
    const value = document.getElementById("pref-value").value.trim();
    if (!value) { alert("請輸入值"); return; }
    try {
        await api("/api/preferences", { method: "POST", body: JSON.stringify({ kind, value }) });
        document.getElementById("pref-value").value = "";
        await loadPrefs();
    } catch (e) { alert("新增失敗：" + e.message); }
}
async function recommendByPref() {
    const el = document.getElementById("pref-status");
    setStatus(el, "推薦中...");
    const min = document.getElementById("pref-min").value;
    const params = new URLSearchParams();
    if (min) params.set("min_score", min);
    try {
        const data = await api(`/api/search/preferences?${params.toString()}`);
        document.getElementById("pref-results").innerHTML = data.items.map(m => cardHTML(m)).join("") ||
            `<div class="status">沒有符合偏好的作品，請先設定偏好。</div>`;
        setStatus(el, `推薦 ${data.total} 部`);
    } catch (e) { setStatus(el, "錯誤：" + e.message, true); }
}

// ---------- detail modal ----------
async function openDetail(id) {
    const modal = document.getElementById("modal");
    const body = document.getElementById("modal-body");
    try {
        const m = await api(`/api/anime/${id}`);
        const cover = m.cover_large || m.cover_medium || "";
        body.innerHTML = `
            <div class="modal-body-top">
                ${cover ? `<img src="${esc(cover)}" alt="">` : ""}
                <div>
                    <h2>${esc(titleOf(m))}</h2>
                    <div class="detail-meta">${esc(m.title_english || "")}</div>
                    <div class="detail-meta">${esc(m.title_native || "")}</div>
                    <div class="detail-meta">${esc(m.status || "")} · ${esc(m.format || "")} · ${esc(m.season || "")} ${esc(m.season_year || "")} · ${esc(m.episodes ?? "?")} 話</div>
                    <div class="detail-meta">⭐ ${esc(m.mean_score ?? "?")} 社群平均 · ♥ 人氣 ${esc(m.popularity ?? 0)} · 🔥 ${esc(m.trending ?? 0)} · ★ ${esc(m.favourites ?? 0)}</div>
                    <div class="tags">${statusTags(m)}${(m.tags || []).slice(0, 6).map(t => `<span class="tag">${esc(t)}</span>`).join("")}</div>
                    ${m.site_url ? `<div class="detail-meta"><a href="${esc(m.site_url)}" target="_blank" rel="noopener">AniList 頁面 ↗</a></div>` : ""}
                </div>
            </div>
            ${(() => {
                const syn = m.synopsis_zh || m.synopsis || "";
                const src = m.synopsis_zh ? "中文劇情（zh-wiki）" : (m.synopsis ? "英文劇情（原文）" : "");
                return syn
                    ? `<div class="syn">${esc(syn.slice(0, 800))}${src ? `<div class="detail-meta">${esc(src)}</div>` : ""}</div>`
                    : `<div class="syn syn-empty">（暫無中文劇情，可點擊上方「補齊中文」）</div>`;
            })()}
            <div class="watch-controls">
                <div class="field">
                    <label>狀態</label>
                    <select id="d-status">
                        ${[["want_to_watch","想看"],["watching","在看"],["completed","已看完"],["dropped","棄追"]]
                            .map(([v, l]) => `<option value="${v}" ${m.watch_status === v ? "selected" : ""}>${l}</option>`).join("")}
                    </select>
                </div>
                <div class="field">
                    <label>進度（話）</label>
                    <input id="d-progress" type="number" min="0" value="${esc(m.my_progress || 0)}">
                </div>
                <div class="field">
                    <label>我的評分 (0-10)</label>
                    <input id="d-score" type="number" min="0" max="10" value="${m.my_score != null ? esc(m.my_score) : ""}">
                </div>
                <div class="field" style="flex:1">
                    <label>備註</label>
                    <input id="d-notes" type="text" value="${esc(m.my_notes || "")}" placeholder="心得...">
                </div>
                <button class="btn primary" onclick="saveFromModal(${m.id})">儲存</button>
                ${m.watch_status ? '<button class="btn" style="background:#ef4444;color:#fff" onclick="deleteFromModal(' + m.id + ')">移除</button>' : ""}
            </div>`;
        modal.classList.remove("hidden");
    } catch (e) { alert("載入失敗：" + e.message); }
}
async function saveFromModal(id) {
    const status = document.getElementById("d-status").value;
    const progress = Number(document.getElementById("d-progress").value || 0);
    const scoreEl = document.getElementById("d-score");
    const score = scoreEl.value === "" ? null : Number(scoreEl.value);
    const notes = document.getElementById("d-notes").value;
    try {
        await api(`/api/anime/${id}/watch`, {
            method: "PUT",
            body: JSON.stringify({ status, progress, personal_score: score, notes }),
        });
        loadWatchlist();
        loadTop();
        loadSeason();
        document.getElementById("modal").classList.add("hidden");
    } catch (e) { alert("儲存失敗：" + e.message); }
}
async function deleteFromModal(id) {
    await deleteWatch(id);
    document.getElementById("modal").classList.add("hidden");
}
document.getElementById("modal").addEventListener("click", (e) => {
    if (e.target.id === "modal") document.getElementById("modal").classList.add("hidden");
});
document.getElementById("modal-close").addEventListener("click", () => {
    document.getElementById("modal").classList.add("hidden");
});

// ---------- Chinese title sync (wikidata/zh-wiki background job) ----------
let _titlePoll = null;
async function startTitleSync() {
    const btn = document.getElementById("titles-sync");
    const st = document.getElementById("titles-status");
    try {
        const r = await api("/api/titles/sync", { method: "POST" });
        setStatus(st, "已開始補齊中文名稱…");
        btn.disabled = true;
        _titlePoll = setInterval(pollTitleSync, 2000);
    } catch (e) {
        setStatus(st, "失敗：" + e.message, true);
    }
}
async function pollTitleSync() {
    const st = document.getElementById("titles-status");
    try {
        const s = await api("/api/titles/status");
        if (s.running) {
            setStatus(st, `補全中… ${s.done}/${s.total}（名 ${s.hit} / 劇情 ${s.syn_hit ?? 0}）`);
        } else {
            clearInterval(_titlePoll);
            _titlePoll = null;
            document.getElementById("titles-sync").disabled = false;
            setStatus(st, s.message || "完成");
            refreshVisible();
        }
    } catch (e) {
        clearInterval(_titlePoll);
        document.getElementById("titles-sync").disabled = false;
    }
}
function refreshVisible() {
    const active = document.querySelector(".tab.active");
    if (!active) return;
    if (active.dataset.tab === "home") loadTop();
    else if (active.dataset.tab === "season") loadSeason();
}

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach((b) => {
    b.addEventListener("click", () => {
        document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
        document.querySelectorAll(".panel").forEach(x => x.classList.remove("active"));
        b.classList.add("active");
        document.getElementById("tab-" + b.dataset.tab).classList.add("active");
        if (b.dataset.tab === "watchlist") loadWatchlist();
        if (b.dataset.tab === "prefs") loadPrefs();
    });
});

// ---------- init ----------
function seasonOf(year, month) { // month 0-based, matches app/anilist.py current_season()
    if (month >= 2 && month <= 4) return "SPRING";
    if (month >= 5 && month <= 7) return "SUMMER";
    if (month >= 8 && month <= 10) return "FALL";
    return "WINTER";
}
function applyCurrentSeasonDefaults() {
    const now = new Date();
    const season = seasonOf(now.getFullYear(), now.getMonth());
    document.getElementById("home-season").value = season;
    document.getElementById("season-pick").value = season;
    document.getElementById("home-year").value = now.getFullYear();
    document.getElementById("season-year").value = now.getFullYear();
}
SEASONS.forEach(s => {
    document.getElementById("home-season").innerHTML += `<option value="${s}">${s}</option>`;
    document.getElementById("season-pick").innerHTML += `<option value="${s}">${s}</option>`;
});
applyCurrentSeasonDefaults();
document.getElementById("home-refresh").addEventListener("click", () => {
    document.getElementById("home-status").dataset.force = "1";
    loadTop();
});
document.getElementById("season-refresh").addEventListener("click", () => {
    document.getElementById("season-status").dataset.force = "1";
    loadSeason();
});
document.getElementById("home-load").addEventListener("click", loadTop);
document.getElementById("season-load").addEventListener("click", loadSeason);
document.getElementById("search-go").addEventListener("click", doSearch);
document.getElementById("search-q").addEventListener("keypress", (e) => { if (e.key === "Enter") doSearch(); });
document.getElementById("watch-refresh").addEventListener("click", loadWatchlist);
document.getElementById("pref-add").addEventListener("click", addPref);
document.getElementById("pref-search").addEventListener("click", recommendByPref);
document.getElementById("titles-sync").addEventListener("click", startTitleSync);

loadGenres();
loadWatchlist();
loadPrefs();
loadTop();