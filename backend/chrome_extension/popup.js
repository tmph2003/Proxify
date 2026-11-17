// ─── Cấu hình Proxy 1-Chạm, Request Blocker (DNR) & DB Capture ─────────────────
document.addEventListener("DOMContentLoaded", async () => {
    const serverConfigForm = document.getElementById("serverConfigForm");
    const serverUrlInput = document.getElementById("serverUrlInput");
    const configStatus = document.getElementById("configStatus");

    const proxyStateBadge = document.getElementById("proxyStateBadge");
    const proxyStateDesc = document.getElementById("proxyStateDesc");
    const toggleProxyBtn = document.getElementById("toggleProxyBtn");

    // ─── Helper tạo DOM an toàn (chống XSS) ───────────────────────────────────
    function setSafeDescription(el, prefixText, boldText, suffixText = "") {
        if (!el) return;
        el.textContent = "";
        if (prefixText) el.appendChild(document.createTextNode(prefixText));
        if (boldText) {
            const b = document.createElement("b");
            b.textContent = boldText;
            el.appendChild(b);
        }
        if (suffixText) el.appendChild(document.createTextNode(suffixText));
    }

    // ─── 1. PROXY CONTROLLER ──────────────────────────────────────────────────
    let isProxyCurrentlyEnabled = false;

    async function refreshProxyStateUI() {
        if (!chrome.proxy || !chrome.proxy.settings) {
            proxyStateBadge.textContent = "CẦN RELOAD";
            proxyStateBadge.className = "proxy-badge locked";
            setSafeDescription(
                proxyStateDesc,
                "Vui lòng vào ",
                "chrome://extensions",
                " bấm Reload (🔄) ở tiện ích Proxify Helper để kích hoạt quyền Proxy."
            );
            toggleProxyBtn.disabled = true;
            toggleProxyBtn.style.opacity = "0.5";
            return;
        }

        try {
            const details = await new Promise((resolve) => {
                chrome.proxy.settings.get({ incognito: false }, resolve);
            });
            if (!details || !details.value) return;
            const mode = details.value.mode;
            const level = details.levelOfControl;

            if (level === "not_controllable" || level === "controlled_by_other_extensions") {
                isProxyCurrentlyEnabled = (mode === "fixed_servers");
                proxyStateBadge.textContent = "BỊ KHÓA (MỞ LẠI CHROME)";
                proxyStateBadge.className = "proxy-badge locked";
                setSafeDescription(
                    proxyStateDesc,
                    "Cửa sổ Chrome này đang bị khóa cờ --proxy-server. Hãy ",
                    "đóng toàn bộ Chrome rồi mở lại 1 lần",
                    " để nút Bật/Tắt có hiệu lực!"
                );
                toggleProxyBtn.textContent = "⚠️ Cần khởi động lại Chrome 1 lần";
                toggleProxyBtn.className = "toggle-proxy-btn turn-off";
            } else if (mode === "fixed_servers") {
                isProxyCurrentlyEnabled = true;
                proxyStateBadge.textContent = "ĐANG BẬT PROXIFY";
                proxyStateBadge.className = "proxy-badge active";
                setSafeDescription(proxyStateDesc, "Traffic mục tiêu đang đi qua ", "Proxify (127.0.0.1:8080)", ".");
                toggleProxyBtn.textContent = "🔴 Tắt Proxy (Về nguyên bản)";
                toggleProxyBtn.className = "toggle-proxy-btn turn-off";
            } else {
                isProxyCurrentlyEnabled = false;
                proxyStateBadge.textContent = "NGUYÊN BẢN (DIRECT)";
                proxyStateBadge.className = "proxy-badge";
                setSafeDescription(proxyStateDesc, "Chrome đang chạy ", "nguyên bản", " (kết nối trực tiếp, không qua Proxify).");
                toggleProxyBtn.textContent = "🟢 Bật Proxy Proxify (127.0.0.1:8080)";
                toggleProxyBtn.className = "toggle-proxy-btn turn-on";
            }
        } catch (err) {
            console.error("Failed to read proxy settings:", err);
        }
    }

    if (toggleProxyBtn) {
        toggleProxyBtn.addEventListener("click", async () => {
            const targetEnable = !isProxyCurrentlyEnabled;
            toggleProxyBtn.disabled = true;
            try {
                await chrome.runtime.sendMessage({
                    type: "SET_PROXY_MODE",
                    enable: targetEnable,
                    host: "127.0.0.1",
                    port: 8080
                });
            } catch (err) {
                console.error("Failed to toggle proxy:", err);
            } finally {
                toggleProxyBtn.disabled = false;
                await refreshProxyStateUI();
            }
        });
    }

    // ─── 2. CUSTOM REQUEST BLOCKER (declarativeNetRequest) ────────────────────
    const blockerStateBadge = document.getElementById("blockerStateBadge");
    const blockerStateDesc = document.getElementById("blockerStateDesc");
    const toggleBlockerBtn = document.getElementById("toggleBlockerBtn");
    const blockerSummary = document.getElementById("blockerSummary");
    const addBlockRuleForm = document.getElementById("addBlockRuleForm");
    const blockPatternInput = document.getElementById("blockPatternInput");
    const blockRuleError = document.getElementById("blockRuleError");
    const quickBlockRow = document.getElementById("quickBlockRow");
    const blockCurrentTabBtn = document.getElementById("blockCurrentTabBtn");
    const blockRuleList = document.getElementById("blockRuleList");
    const clearBlockRulesBtn = document.getElementById("clearBlockRulesBtn");

    let isBlockerEnabled = true;
    let blockRules = [];
    let activeTabDomain = "";

    function showBlockerError(msg) {
        if (!blockRuleError || !blockPatternInput) return;
        if (msg) {
            blockRuleError.textContent = msg;
            blockRuleError.style.display = "block";
            blockPatternInput.setAttribute("aria-invalid", "true");
        } else {
            blockRuleError.textContent = "";
            blockRuleError.style.display = "none";
            blockPatternInput.removeAttribute("aria-invalid");
        }
    }

    if (blockPatternInput) {
        blockPatternInput.addEventListener("input", () => {
            showBlockerError("");
        });
    }

    function cleanUserPattern(raw) {
        let p = (raw || "").trim();
        if (!p) return "";
        // Protect user from accidentally blocking localhost / Proxify Control Plane
        const lower = p.toLowerCase();
        if (
            lower === "localhost" ||
            lower === "127.0.0.1" ||
            lower.startsWith("127.0.0.1:") ||
            lower.startsWith("http://127.0.0.1") ||
            lower.startsWith("http://localhost")
        ) {
            throw new Error("Không được chặn localhost / 127.0.0.1 để đảm bảo kết nối Proxify!");
        }
        return p;
    }

    async function persistBlockerState() {
        if (chrome.storage && chrome.storage.local) {
            await chrome.storage.local.set({
                blockerEnabled: isBlockerEnabled,
                blockRules
            });
        }
        try {
            const syncRes = await chrome.runtime.sendMessage({ type: "SYNC_BLOCK_RULES" });
            if (syncRes && !syncRes.ok && syncRes.error) {
                showBlockerError(`Lỗi cú pháp rule DNR: ${syncRes.error}`);
            }
        } catch (err) {
            console.error("Failed to sync block rules:", err);
        }
        renderBlockerUI();
    }

    function renderBlockerUI() {
        const activeCount = blockRules.filter(r => r && r.enabled !== false).length;

        if (blockerStateBadge && blockerStateDesc && toggleBlockerBtn) {
            if (isBlockerEnabled) {
                blockerStateBadge.textContent = activeCount > 0 ? `ĐANG CHẶN (${activeCount})` : "ĐANG BẬT";
                blockerStateBadge.className = activeCount > 0 ? "proxy-badge warn" : "proxy-badge active";
                setSafeDescription(
                    blockerStateDesc,
                    "Đang thực thi ",
                    `${activeCount} quy tắc chặn`,
                    " trực tiếp ở tầng mạng Chrome."
                );
                toggleBlockerBtn.textContent = "🔴 Tạm tắt Bộ Chặn Request";
                toggleBlockerBtn.className = "toggle-proxy-btn turn-off";
            } else {
                blockerStateBadge.textContent = "ĐANG TẮT";
                blockerStateBadge.className = "proxy-badge";
                setSafeDescription(
                    blockerStateDesc,
                    "Bộ chặn đang ",
                    "tạm dừng",
                    ` (giữ nguyên ${blockRules.length} quy tắc đã lưu).`
                );
                toggleBlockerBtn.textContent = "🟢 Bật Bộ Chặn Request";
                toggleBlockerBtn.className = "toggle-proxy-btn turn-on";
            }
        }

        if (blockerSummary) {
            blockerSummary.textContent = `🛑 Quy tắc chặn (${activeCount}/${blockRules.length} đang bật)`;
            blockerSummary.style.color = (isBlockerEnabled && activeCount > 0) ? "#fcd34d" : "#93c5fd";
        }

        if (quickBlockRow && blockCurrentTabBtn) {
            const isLocalTab = activeTabDomain === "localhost" || activeTabDomain === "127.0.0.1";
            if (activeTabDomain && !isLocalTab) {
                const alreadyBlocked = blockRules.some(
                    r => r.pattern.toLowerCase() === activeTabDomain || r.pattern.toLowerCase() === `*.${activeTabDomain}`
                );
                quickBlockRow.hidden = alreadyBlocked;
                blockCurrentTabBtn.textContent = `➕ Chặn nhanh ${activeTabDomain}`;
            } else {
                quickBlockRow.hidden = true;
            }
        }

        if (!blockRuleList) return;
        blockRuleList.textContent = "";

        if (blockRules.length === 0) {
            const empty = document.createElement("div");
            empty.className = "empty-state";
            empty.textContent = "Chưa có quy tắc nào. Nhập domain hoặc URL pattern ở trên để chặn.";
            blockRuleList.appendChild(empty);
            return;
        }

        for (const rule of blockRules) {
            const row = document.createElement("div");
            row.className = `rule-row${rule.enabled === false ? " disabled" : ""}`;

            const label = document.createElement("label");
            label.className = "rule-label";

            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.checked = rule.enabled !== false;
            cb.addEventListener("change", async () => {
                rule.enabled = cb.checked;
                await persistBlockerState();
            });

            const span = document.createElement("span");
            span.className = "rule-pattern";
            span.textContent = rule.pattern;

            label.appendChild(cb);
            label.appendChild(span);

            const delBtn = document.createElement("button");
            delBtn.type = "button";
            delBtn.className = "delete-rule-btn";
            delBtn.textContent = "✕";
            delBtn.setAttribute("aria-label", `Xóa quy tắc ${rule.pattern}`);
            delBtn.addEventListener("click", async () => {
                blockRules = blockRules.filter(x => x.id !== rule.id);
                await persistBlockerState();
            });

            row.appendChild(label);
            row.appendChild(delBtn);
            blockRuleList.appendChild(row);
        }
    }

    async function addNewBlockPattern(rawInput) {
        showBlockerError("");
        let pattern = "";
        try {
            pattern = cleanUserPattern(rawInput);
        } catch (validationErr) {
            showBlockerError(validationErr.message);
            if (blockPatternInput) blockPatternInput.focus();
            return false;
        }

        if (!pattern) {
            showBlockerError("Vui lòng nhập domain hoặc URL pattern cần chặn.");
            if (blockPatternInput) blockPatternInput.focus();
            return false;
        }

        if (/[^\x00-\x7F]/.test(pattern) && !pattern.includes(".")) {
            showBlockerError("Pattern chỉ hỗ trợ ký tự ASCII hợp lệ trong URL.");
            if (blockPatternInput) blockPatternInput.focus();
            return false;
        }

        const existing = blockRules.find(r => r.pattern.toLowerCase() === pattern.toLowerCase());
        if (existing) {
            existing.enabled = true;
        } else {
            const id = typeof crypto !== "undefined" && crypto.randomUUID
                ? crypto.randomUUID()
                : `rule_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
            blockRules.unshift({
                id,
                pattern,
                enabled: true,
                createdAt: Date.now()
            });
        }

        isBlockerEnabled = true;
        await persistBlockerState();
        return true;
    }

    if (toggleBlockerBtn) {
        toggleBlockerBtn.addEventListener("click", async () => {
            isBlockerEnabled = !isBlockerEnabled;
            await persistBlockerState();
        });
    }

    if (addBlockRuleForm && blockPatternInput) {
        addBlockRuleForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const ok = await addNewBlockPattern(blockPatternInput.value);
            if (ok) {
                blockPatternInput.value = "";
            }
        });
    }

    if (blockCurrentTabBtn) {
        blockCurrentTabBtn.addEventListener("click", async () => {
            if (activeTabDomain) {
                await addNewBlockPattern(activeTabDomain);
            }
        });
    }

    if (clearBlockRulesBtn) {
        clearBlockRulesBtn.addEventListener("click", async () => {
            if (blockRules.length === 0) return;
            blockRules = [];
            showBlockerError("");
            await persistBlockerState();
        });
    }

    // ─── 3. DB CAPTURE CONTROLLER ─────────────────────────────────────────────
    const dbStateBadge = document.getElementById("dbStateBadge");
    const dbStateDesc = document.getElementById("dbStateDesc");
    const toggleDbBtn = document.getElementById("toggleDbBtn");
    const dbDomainSummary = document.getElementById("dbDomainSummary");
    const dbDomainList = document.getElementById("dbDomainList");
    const addDbDomainForm = document.getElementById("addDbDomainForm");
    const customDomainInput = document.getElementById("customDomainInput");
    const clearDomainsBtn = document.getElementById("clearDomainsBtn");

    let isDbCurrentlyEnabled = false;
    let dbAllowedDomains = [];
    let capturedDomains = [];
    let currentServerUrl = "http://127.0.0.1:8888";

    function updateDomainSummaryText() {
        if (!dbDomainSummary) return;
        if (dbAllowedDomains.length > 0) {
            dbDomainSummary.textContent = `🎯 Lọc Ghi DB (${dbAllowedDomains.length} domain)`;
            dbDomainSummary.style.color = "#34d399";
        } else {
            dbDomainSummary.textContent = "🎯 Lọc Ghi DB (Tất cả)";
            dbDomainSummary.style.color = "#93c5fd";
        }
    }

    async function saveAllowedDomainsToServer(newDomains) {
        dbAllowedDomains = Array.from(new Set(newDomains.map(d => d.trim().toLowerCase()).filter(Boolean)));
        updateDomainSummaryText();
        renderDbDomainList();
        try {
            await fetch(`${currentServerUrl}/api/toggle_db`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ allowed_domains: dbAllowedDomains })
            });
        } catch (e) {
            console.error("Failed to save allowed_domains:", e);
        }
    }

    function renderDbDomainList() {
        if (!dbDomainList) return;
        updateDomainSummaryText();

        const domainMap = new Map();
        if (activeTabDomain) domainMap.set(activeTabDomain, null);

        for (const d of dbAllowedDomains) {
            if (!domainMap.has(d)) domainMap.set(d, null);
        }

        for (const item of capturedDomains) {
            if (item && item.domain) {
                domainMap.set(item.domain, item.count);
            }
        }

        dbDomainList.textContent = "";
        if (domainMap.size === 0) {
            const empty = document.createElement("div");
            empty.className = "empty-state";
            empty.textContent = "Chưa ghi nhận domain nào.";
            dbDomainList.appendChild(empty);
            return;
        }

        for (const [dom, count] of domainMap.entries()) {
            const label = document.createElement("label");
            label.className = "domain-item";

            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = dom;
            cb.checked = dbAllowedDomains.includes(dom);
            cb.addEventListener("change", async () => {
                if (cb.checked) {
                    await saveAllowedDomainsToServer([...dbAllowedDomains, dom]);
                } else {
                    await saveAllowedDomainsToServer(dbAllowedDomains.filter(x => x !== dom));
                }
            });

            const span = document.createElement("span");
            span.appendChild(document.createTextNode(dom));

            if (count !== null && count !== undefined) {
                const small = document.createElement("small");
                small.style.color = "#71717a";
                small.textContent = ` (${count})`;
                span.appendChild(small);
            } else if (dom === activeTabDomain) {
                const small = document.createElement("small");
                small.style.color = "#60a5fa";
                small.textContent = " (Tab hiện tại)";
                span.appendChild(small);
            }

            label.appendChild(cb);
            label.appendChild(span);
            dbDomainList.appendChild(label);
        }
    }

    if (addDbDomainForm && customDomainInput) {
        addDbDomainForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            let val = customDomainInput.value.trim().toLowerCase();
            if (!val) return;
            try {
                if (val.includes("://")) val = new URL(val).hostname;
            } catch (err) {
                // Keep raw domain input if URL parsing fails
            }
            customDomainInput.value = "";
            if (val) {
                await saveAllowedDomainsToServer([...dbAllowedDomains, val]);
            }
        });
    }

    if (clearDomainsBtn) {
        clearDomainsBtn.addEventListener("click", async () => {
            await saveAllowedDomainsToServer([]);
        });
    }

    function renderDbStateUI(enabled, errorMsg = null) {
        if (!dbStateBadge || !dbStateDesc || !toggleDbBtn) return;
        if (errorMsg) {
            dbStateBadge.textContent = "MẤT KẾT NỐI";
            dbStateBadge.className = "proxy-badge locked";
            dbStateDesc.textContent = "";
            const errSpan = document.createElement("span");
            errSpan.style.color = "#fca5a5";
            errSpan.textContent = errorMsg;
            dbStateDesc.appendChild(errSpan);
            toggleDbBtn.textContent = "🔄 Thử kết nối lại Server";
            toggleDbBtn.className = "toggle-proxy-btn turn-off";
            return;
        }
        isDbCurrentlyEnabled = Boolean(enabled);
        if (isDbCurrentlyEnabled) {
            dbStateBadge.textContent = "ĐANG GHI DB";
            dbStateBadge.className = "proxy-badge active";
            setSafeDescription(dbStateDesc, "Server đang ", "lưu gói tin vào PostgreSQL", ".");
            toggleDbBtn.textContent = "🔴 Tắt Ghi DB";
            toggleDbBtn.className = "toggle-proxy-btn turn-off";
        } else {
            dbStateBadge.textContent = "ĐANG TẮT";
            dbStateBadge.className = "proxy-badge";
            setSafeDescription(dbStateDesc, "Chế độ ", "Chỉ xem Live", " (Không ghi xuống PostgreSQL).");
            toggleDbBtn.textContent = "🟢 Bật Ghi DB (PostgreSQL)";
            toggleDbBtn.className = "toggle-proxy-btn turn-on";
        }
    }

    async function fetchDbStateFromServer(baseUrl) {
        let cleanUrl = (baseUrl || currentServerUrl || "http://127.0.0.1:8888").replace(/\/+$/, "");
        if (cleanUrl === "http://127.0.0.1:8080" || cleanUrl === "http://localhost:8080") {
            cleanUrl = cleanUrl.replace(":8080", ":8888");
            if (serverUrlInput) serverUrlInput.value = cleanUrl;
            if (chrome.storage && chrome.storage.local) {
                await chrome.storage.local.set({ serverUrl: cleanUrl });
            }
        }
        currentServerUrl = cleanUrl;
        try {
            let domRes = null;
            const cfgPromise = fetch(`${cleanUrl}/api/config`, { method: "GET" });
            try {
                domRes = await fetch(`${cleanUrl}/api/domains`, { method: "GET" });
            } catch (domErr) {
                domRes = null;
            }
            const cfgRes = await cfgPromise;
            if (!cfgRes.ok) throw new Error(`HTTP ${cfgRes.status}`);
            const data = await cfgRes.json();
            if (Array.isArray(data.db_allowed_domains)) {
                dbAllowedDomains = data.db_allowed_domains;
            }
            if (domRes && domRes.ok) {
                const domData = await domRes.json();
                if (Array.isArray(domData)) capturedDomains = domData;
                else if (domData && Array.isArray(domData.domains)) capturedDomains = domData.domains;
            }
            const dbEnabled = data.db_integration_enabled !== undefined ? data.db_integration_enabled : data.save_to_db;
            renderDbStateUI(Boolean(dbEnabled));
            renderDbDomainList();
        } catch (err) {
            renderDbStateUI(false, `Không kết nối được Proxify (${cleanUrl})`);
        }
    }

    if (toggleDbBtn) {
        toggleDbBtn.addEventListener("click", async () => {
            if (dbStateBadge && dbStateBadge.textContent === "MẤT KẾT NỐI") {
                await fetchDbStateFromServer(currentServerUrl);
                return;
            }
            const targetState = !isDbCurrentlyEnabled;
            toggleDbBtn.disabled = true;
            try {
                const res = await fetch(`${currentServerUrl}/api/toggle_db`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ enabled: targetState })
                });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data = await res.json();
                const dbEnabled = data.db_integration_enabled !== undefined ? data.db_integration_enabled : data.save_to_db;
                renderDbStateUI(Boolean(dbEnabled));
            } catch (err) {
                renderDbStateUI(isDbCurrentlyEnabled, `Lỗi khi đổi trạng thái DB (${err.message})`);
            } finally {
                toggleDbBtn.disabled = false;
            }
        });
    }

    if (serverConfigForm) {
        serverConfigForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            let sUrl = (serverUrlInput ? serverUrlInput.value : "").trim().replace(/\/+$/, "");
            if (!sUrl) sUrl = "http://127.0.0.1:8888";

            if (chrome.storage && chrome.storage.local) {
                await chrome.storage.local.set({ serverUrl: sUrl });
            }
            await fetchDbStateFromServer(sUrl);
            if (configStatus) {
                configStatus.textContent = "✅ Đã lưu!";
                configStatus.style.display = "block";
                setTimeout(() => {
                    configStatus.style.display = "none";
                }, 2500);
            }
        });
    }

    // ─── KHỞI TẠO DỮ LIỆU BAN ĐẦU ─────────────────────────────────────────────
    await refreshProxyStateUI();

    if (chrome.tabs && chrome.tabs.query) {
        try {
            const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
            if (tabs && tabs[0] && tabs[0].url) {
                const u = new URL(tabs[0].url);
                if (u.protocol === "http:" || u.protocol === "https:") {
                    activeTabDomain = u.hostname.replace(/^www\./, "").toLowerCase();
                }
            }
        } catch (err) {
            // Ignore non-standard tab URLs (e.g., chrome://)
        }
    }

    if (chrome.storage && chrome.storage.local) {
        const items = await chrome.storage.local.get({
            serverUrl: "http://127.0.0.1:8888",
            blockerEnabled: true,
            blockRules: []
        });
        const sUrl = items.serverUrl || "http://127.0.0.1:8888";
        isBlockerEnabled = items.blockerEnabled !== false;
        blockRules = Array.isArray(items.blockRules) ? items.blockRules : [];

        if (serverUrlInput) serverUrlInput.value = sUrl;
        renderBlockerUI();
        renderDbDomainList();
        await fetchDbStateFromServer(sUrl);
    } else {
        renderBlockerUI();
        await fetchDbStateFromServer("http://127.0.0.1:8888");
    }
});
