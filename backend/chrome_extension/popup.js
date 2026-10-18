// ─── Cấu hình Proxy 1-Chạm & Server URL / DB Capture ─────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    const serverUrlInput = document.getElementById("serverUrlInput");
    const saveConfigBtn = document.getElementById("saveConfigBtn");
    const configStatus = document.getElementById("configStatus");

    const proxyStateBadge = document.getElementById("proxyStateBadge");
    const proxyStateDesc = document.getElementById("proxyStateDesc");
    const toggleProxyBtn = document.getElementById("toggleProxyBtn");

    let isProxyCurrentlyEnabled = false;

    function refreshProxyStateUI() {
        if (!chrome.proxy || !chrome.proxy.settings) {
            proxyStateBadge.innerText = "CẦN RELOAD";
            proxyStateBadge.className = "proxy-badge locked";
            proxyStateDesc.innerHTML = "Vui lòng vào <b>chrome://extensions</b> bấm biểu tượng <b>Reload (🔄)</b> ở tiện ích Proxify Helper để kích hoạt quyền Proxy.";
            toggleProxyBtn.disabled = true;
            toggleProxyBtn.style.opacity = "0.5";
            return;
        }

        chrome.proxy.settings.get({ incognito: false }, (details) => {
            if (!details || !details.value) return;
            const mode = details.value.mode;
            const level = details.levelOfControl;

            if (level === "not_controllable" || level === "controlled_by_other_extensions") {
                isProxyCurrentlyEnabled = (mode === "fixed_servers");
                proxyStateBadge.innerText = "BỊ KHÓA (CẦN MỞ LẠI CHROME)";
                proxyStateBadge.className = "proxy-badge locked";
                proxyStateDesc.innerHTML =
                    "Cửa sổ Chrome này đang chạy từ phiên cũ có gắn cờ <code>--proxy-server</code>.<br>" +
                    "👉 Hãy <b>đóng toàn bộ Chrome rồi mở lại 1 lần</b> để nút Bật/Tắt có hiệu lực tức thì!";
                toggleProxyBtn.innerText = "⚠️ Cần khởi động lại Chrome 1 lần";
                toggleProxyBtn.className = "toggle-proxy-btn turn-off";
            } else if (mode === "fixed_servers") {
                isProxyCurrentlyEnabled = true;
                proxyStateBadge.innerText = "ĐANG BẬT PROXIFY";
                proxyStateBadge.className = "proxy-badge active";
                proxyStateDesc.innerHTML = "Traffic mục tiêu đang đi qua <b>Proxify (127.0.0.1:8080)</b>.";
                toggleProxyBtn.innerText = "🔴 Tắt Proxy (Về nguyên bản)";
                toggleProxyBtn.className = "toggle-proxy-btn turn-off";
            } else {
                isProxyCurrentlyEnabled = false;
                proxyStateBadge.innerText = "NGUYÊN BẢN (DIRECT)";
                proxyStateBadge.className = "proxy-badge";
                proxyStateDesc.innerHTML = "Chrome đang chạy <b>nguyên bản</b> (kết nối trực tiếp, không qua Proxify).";
                toggleProxyBtn.innerText = "🟢 Bật Proxy Proxify (127.0.0.1:8080)";
                toggleProxyBtn.className = "toggle-proxy-btn turn-on";
            }
        });
    }

    refreshProxyStateUI();

    if (toggleProxyBtn) {
        toggleProxyBtn.addEventListener("click", () => {
            const targetEnable = !isProxyCurrentlyEnabled;
            toggleProxyBtn.disabled = true;
            chrome.runtime.sendMessage(
                { type: "SET_PROXY_MODE", enable: targetEnable, host: "127.0.0.1", port: 8080 },
                () => {
                    toggleProxyBtn.disabled = false;
                    refreshProxyStateUI();
                }
            );
        });
    }

    const dbStateBadge = document.getElementById("dbStateBadge");
    const dbStateDesc = document.getElementById("dbStateDesc");
    const toggleDbBtn = document.getElementById("toggleDbBtn");
    const dbDomainSummary = document.getElementById("dbDomainSummary");
    const dbDomainList = document.getElementById("dbDomainList");
    const customDomainInput = document.getElementById("customDomainInput");
    const addDomainBtn = document.getElementById("addDomainBtn");
    const clearDomainsBtn = document.getElementById("clearDomainsBtn");

    let isDbCurrentlyEnabled = false;
    let dbAllowedDomains = [];
    let capturedDomains = [];
    let activeTabDomain = "";
    let currentServerUrl = "http://127.0.0.1:8888";

    if (chrome.tabs && chrome.tabs.query) {
        chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
            if (tabs && tabs[0] && tabs[0].url) {
                try {
                    const u = new URL(tabs[0].url);
                    if (u.protocol === "http:" || u.protocol === "https:") {
                        activeTabDomain = u.hostname.replace(/^www\./, "");
                        renderDbDomainList();
                    }
                } catch (e) {}
            }
        });
    }

    function updateDomainSummaryText() {
        if (!dbDomainSummary) return;
        if (dbAllowedDomains.length > 0) {
            dbDomainSummary.innerText = `🎯 Lọc Ghi DB (${dbAllowedDomains.length} domain)`;
            dbDomainSummary.style.color = "#34d399";
        } else {
            dbDomainSummary.innerText = "🎯 Lọc Ghi DB (Tất cả)";
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

        dbAllowedDomains.forEach(d => {
            if (!domainMap.has(d)) domainMap.set(d, null);
        });

        capturedDomains.forEach(item => {
            if (item && item.domain) {
                domainMap.set(item.domain, item.count);
            }
        });

        dbDomainList.innerHTML = "";
        for (const [dom, count] of domainMap.entries()) {
            const label = document.createElement("label");
            label.className = "domain-item";

            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = dom;
            cb.checked = dbAllowedDomains.includes(dom);
            cb.addEventListener("change", () => {
                if (cb.checked) {
                    saveAllowedDomainsToServer([...dbAllowedDomains, dom]);
                } else {
                    saveAllowedDomainsToServer(dbAllowedDomains.filter(x => x !== dom));
                }
            });

            const span = document.createElement("span");
            span.innerHTML = count !== null
                ? `${dom} <small style="color:#71717a">(${count})</small>`
                : `${dom} ${dom === activeTabDomain ? '<small style="color:#60a5fa">(Tab hiện tại)</small>' : ''}`;

            label.appendChild(cb);
            label.appendChild(span);
            dbDomainList.appendChild(label);
        }
    }

    if (addDomainBtn && customDomainInput) {
        const handleAddCustom = () => {
            let val = customDomainInput.value.trim().toLowerCase();
            if (!val) return;
            try {
                if (val.includes("://")) val = new URL(val).hostname;
            } catch (e) {}
            customDomainInput.value = "";
            if (val) {
                saveAllowedDomainsToServer([...dbAllowedDomains, val]);
            }
        };
        addDomainBtn.addEventListener("click", handleAddCustom);
        customDomainInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") handleAddCustom();
        });
    }

    if (clearDomainsBtn) {
        clearDomainsBtn.addEventListener("click", () => {
            saveAllowedDomainsToServer([]);
        });
    }

    function renderDbStateUI(enabled, errorMsg = null) {
        if (!dbStateBadge || !dbStateDesc || !toggleDbBtn) return;
        if (errorMsg) {
            dbStateBadge.innerText = "MẤT KẾT NỐI";
            dbStateBadge.className = "proxy-badge locked";
            dbStateDesc.innerHTML = `<span style="color:#fca5a5">${errorMsg}</span>`;
            toggleDbBtn.innerText = "🔄 Thử kết nối lại Server";
            toggleDbBtn.className = "toggle-proxy-btn turn-off";
            return;
        }
        isDbCurrentlyEnabled = Boolean(enabled);
        if (isDbCurrentlyEnabled) {
            dbStateBadge.innerText = "ĐANG GHI DB";
            dbStateBadge.className = "proxy-badge active";
            dbStateDesc.innerHTML = "Server đang <b>lưu gói tin vào PostgreSQL</b>.";
            toggleDbBtn.innerText = "🔴 Tắt Ghi DB";
            toggleDbBtn.className = "toggle-proxy-btn turn-off";
        } else {
            dbStateBadge.innerText = "ĐANG TẮT";
            dbStateBadge.className = "proxy-badge";
            dbStateDesc.innerHTML = "Chế độ <b>Chỉ xem Live</b> (Không ghi xuống PostgreSQL).";
            toggleDbBtn.innerText = "🟢 Bật Ghi DB (PostgreSQL)";
            toggleDbBtn.className = "toggle-proxy-btn turn-on";
        }
    }

    async function fetchDbStateFromServer(baseUrl) {
        const cleanUrl = (baseUrl || currentServerUrl || "http://127.0.0.1:8888").replace(/\/+$/, "");
        currentServerUrl = cleanUrl;
        try {
            const [cfgRes, domRes] = await Promise.all([
                fetch(`${cleanUrl}/api/config`, { method: "GET" }),
                fetch(`${cleanUrl}/api/domains`, { method: "GET" }).catch(() => null)
            ]);
            if (!cfgRes.ok) throw new Error(`HTTP ${cfgRes.status}`);
            const data = await cfgRes.json();
            if (Array.isArray(data.db_allowed_domains)) {
                dbAllowedDomains = data.db_allowed_domains;
            }
            if (domRes && domRes.ok) {
                const domData = await domRes.json();
                if (Array.isArray(domData)) capturedDomains = domData;
            }
            renderDbStateUI(Boolean(data.db_integration_enabled));
            renderDbDomainList();
        } catch (err) {
            renderDbStateUI(false, `Không kết nối được Proxify (${cleanUrl})`);
        }
    }

    if (toggleDbBtn) {
        toggleDbBtn.addEventListener("click", async () => {
            if (dbStateBadge && dbStateBadge.innerText === "MẤT KẾT NỐI") {
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
                renderDbStateUI(Boolean(data.db_integration_enabled));
            } catch (err) {
                renderDbStateUI(isDbCurrentlyEnabled, `Lỗi khi đổi trạng thái DB (${err.message})`);
            } finally {
                toggleDbBtn.disabled = false;
            }
        });
    }

    if (chrome.storage && chrome.storage.local) {
        chrome.storage.local.get({ serverUrl: "http://127.0.0.1:8888" }, (items) => {
            const sUrl = items.serverUrl || "http://127.0.0.1:8888";
            if (serverUrlInput) serverUrlInput.value = sUrl;
            fetchDbStateFromServer(sUrl);
        });
    } else {
        fetchDbStateFromServer("http://127.0.0.1:8888");
    }

    if (saveConfigBtn) {
        saveConfigBtn.addEventListener("click", () => {
            let sUrl = (serverUrlInput ? serverUrlInput.value : "").trim().replace(/\/+$/, "");
            if (!sUrl) sUrl = "http://127.0.0.1:8888";

            chrome.storage.local.set({ serverUrl: sUrl }, () => {
                fetchDbStateFromServer(sUrl);
                if (configStatus) {
                    configStatus.innerText = "✅ Đã lưu!";
                    configStatus.style.display = "block";
                    setTimeout(() => { configStatus.style.display = "none"; }, 2500);
                }
            });
        });
    }
});
