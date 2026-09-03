document.getElementById('getCookieBtn').addEventListener('click', async () => {
    const status = document.getElementById('status');
    const btn = document.getElementById('getCookieBtn');

    btn.disabled = true;
    btn.style.opacity = '0.5';
    status.innerText = "Đang kiểm tra tab Facebook...";
    status.style.color = "white";

    try {
        // 1. Tìm Tab Facebook đang mở
        let targetTabId = null;
        const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (activeTab && activeTab.url && activeTab.url.includes("facebook.com")) {
            targetTabId = activeTab.id;
        } else {
            const allTabs = await chrome.tabs.query({});
            const fbTab = allTabs.find(t => t.url && t.url.includes("facebook.com"));
            if (fbTab) {
                targetTabId = fbTab.id;
            }
        }

        if (!targetTabId) {
            status.innerHTML = "❌ <b>Không tìm thấy tab Facebook nào!</b><br><small style='color:#fca5a5'>Vui lòng mở 1 tab Facebook (facebook.com) và đăng nhập trước khi bấm nút này.</small>";
            status.style.color = "#ef4444";
            btn.disabled = false;
            btn.style.opacity = '1';
            return;
        }

        status.innerText = "Đang trích xuất Token từ tab Facebook...";

        // 2. Inject script vào tab Facebook để trích xuất fb_dtsg, User ID và SiteData
        let fb_dtsg = "";
        let lsd = "";
        let sd = null;
        let userId = "";

        try {
            const results = await chrome.scripting.executeScript({
                target: { tabId: targetTabId },
                world: "MAIN",
                func: () => {
                    let res = { dtsg: "", lsd: "", user: "", sd: null, docCookie: "" };

                    // 1. Extract User ID
                    try {
                        if (typeof require === "function") {
                            try { res.user = String(require("CurrentUserInitialData").USER_ID || require("CurrentUserInitialData").ACCOUNT_ID || ""); } catch (e) { }
                            if (!res.user || res.user === "0") {
                                try { res.user = String(require("Env").USER_ID || require("Env").user || ""); } catch (e) { }
                            }
                        }
                    } catch (e) { }

                    if (!res.user || res.user === "0") {
                        try {
                            const m = document.documentElement.innerHTML.match(/["'](?:USER_ID|actorID|current_user_id)["']\s*:\s*["'](\d+)["']/);
                            if (m) res.user = m[1];
                        } catch (e) { }
                    }

                    // 2. Extract fb_dtsg
                    try {
                        if (typeof require === "function") {
                            try { const d = require("DTSGInitialData"); if (d && d.token) res.dtsg = d.token; } catch (e) { }
                            if (!res.dtsg) { try { const d = require("DTSGInitData"); if (d && d.token) res.dtsg = d.token; } catch (e) { } }
                            if (!res.dtsg) { try { const d = require("DTSG"); if (d && d.token) res.dtsg = d.token; } catch (e) { } }
                        }
                    } catch (e) { }

                    if (!res.dtsg && window.__fb_dtsg) {
                        res.dtsg = window.__fb_dtsg;
                    }

                    if (!res.dtsg) {
                        try {
                            const inputEl = document.querySelector('input[name="fb_dtsg"]');
                            if (inputEl && inputEl.value) res.dtsg = inputEl.value;
                        } catch (e) { }
                    }

                    if (!res.dtsg) {
                        try {
                            const m = document.documentElement.innerHTML.match(/["'](?:DTSGInitialData|DTSGInitData)["'],\[\],\{["']token["']:["']([^"']+)["']/);
                            if (m) res.dtsg = m[1];
                        } catch (e) { }
                    }

                    if (!res.dtsg) {
                        try {
                            const m = document.documentElement.innerHTML.match(/name="fb_dtsg"\s*value="([^"]+)"/);
                            if (m) res.dtsg = m[1];
                        } catch (e) { }
                    }

                    // 3. Extract LSD
                    try {
                        if (typeof require === "function") {
                            try { const l = require("LSD"); if (l && l.token) res.lsd = l.token; } catch (e) { }
                        }
                    } catch (e) { }

                    if (!res.lsd) {
                        try {
                            const inputLsd = document.querySelector('input[name="lsd"]');
                            if (inputLsd && inputLsd.value) res.lsd = inputLsd.value;
                        } catch (e) { }
                    }

                    // 4. SiteData
                    try {
                        if (typeof require === "function") {
                            const sdObj = require("SiteData");
                            if (sdObj) {
                                res.sd = {
                                    rev: String(sdObj.revision || ""),
                                    hsi: String(sdObj.hsi || ""),
                                    spin_r: String(sdObj.__spin_r || ""),
                                    spin_b: String(sdObj.__spin_b || ""),
                                    spin_t: String(sdObj.__spin_t || ""),
                                    hs: String(sdObj.haste_session || ""),
                                    dpr: String(sdObj.pr || "1"),
                                    ccg: String(sdObj.connectionClass || "GOOD")
                                };
                            }
                        }
                    } catch (e) { }

                    try { res.docCookie = document.cookie || ""; } catch (e) { }

                    return res;
                }
            });

            if (results && results[0] && results[0].result) {
                let r = results[0].result;
                fb_dtsg = r.dtsg || "";
                lsd = r.lsd || "";
                sd = r.sd || null;
                userId = r.user || "";
            }
        } catch (e) {
            console.error("Script error:", e);
        }

        // 3. Quét toàn bộ Cookie của Facebook từ Cookie API (hỗ trợ cả Partitioned Cookies / CHIPS)
        status.innerText = "Đang quét Cookie...";
        let cookieMap = new Map();

        const addCookie = (c) => {
            if (c && c.name && c.value) {
                cookieMap.set(c.name, c.value);
            }
        };

        const targetDomains = [
            ".facebook.com",
            "facebook.com",
            "www.facebook.com",
            "m.facebook.com",
            "web.facebook.com"
        ];

        const baseUrls = [
            "https://www.facebook.com",
            "https://facebook.com",
            "https://m.facebook.com",
            "https://web.facebook.com"
        ];

        // 3.1. Quét theo domain chuẩn (unpartitioned)
        for (const dom of targetDomains) {
            try {
                const list = await chrome.cookies.getAll({ domain: dom });
                if (Array.isArray(list)) list.forEach(addCookie);
            } catch (e) { }
        }

        // 3.2. Quét Partitioned Cookies (CHIPS) - Rất quan trọng trên Chrome 118+
        for (const dom of targetDomains) {
            try {
                const list = await chrome.cookies.getAll({ domain: dom, partitionKey: {} });
                if (Array.isArray(list)) list.forEach(addCookie);
            } catch (e) { }
        }

        // 3.3. Quét theo partition topLevelSite cụ thể
        for (const topSite of ["https://facebook.com", "https://www.facebook.com", "https://m.facebook.com"]) {
            try {
                const list = await chrome.cookies.getAll({ partitionKey: { topLevelSite: topSite } });
                if (Array.isArray(list)) list.forEach(addCookie);
            } catch (e) { }
        }

        // 3.4. Quét theo Tab URL nếu có
        try {
            const targetTab = await chrome.tabs.get(targetTabId);
            if (targetTab && targetTab.url) {
                try {
                    const list = await chrome.cookies.getAll({ url: targetTab.url });
                    if (Array.isArray(list)) list.forEach(addCookie);
                } catch (e) { }
                try {
                    const list = await chrome.cookies.getAll({ url: targetTab.url, partitionKey: {} });
                    if (Array.isArray(list)) list.forEach(addCookie);
                } catch (e) { }
            }
        } catch (e) { }

        // 3.5. Quét tất cả Cookie Stores
        try {
            const stores = await chrome.cookies.getAllCookieStores();
            for (const store of stores) {
                for (const url of baseUrls) {
                    try {
                        const list = await chrome.cookies.getAll({ url: url, storeId: store.id });
                        if (Array.isArray(list)) list.forEach(addCookie);
                    } catch (e) { }
                    try {
                        const list = await chrome.cookies.getAll({ url: url, storeId: store.id, partitionKey: {} });
                        if (Array.isArray(list)) list.forEach(addCookie);
                    } catch (e) { }
                }
            }
        } catch (e) { }

        // 3.6. Quét toàn bộ kho cookie và lọc tên miền Facebook (bắt trọn mọi ngóc ngách)
        try {
            const allUnpart = await chrome.cookies.getAll({});
            if (Array.isArray(allUnpart)) {
                allUnpart.forEach(c => {
                    if (c && c.domain && (c.domain.includes("facebook.com") || c.domain.includes("fb.com"))) {
                        addCookie(c);
                    }
                });
            }
        } catch (e) { }

        try {
            const allPart = await chrome.cookies.getAll({ partitionKey: {} });
            if (Array.isArray(allPart)) {
                allPart.forEach(c => {
                    if (c && c.domain && (c.domain.includes("facebook.com") || c.domain.includes("fb.com"))) {
                        addCookie(c);
                    }
                });
            }
        } catch (e) { }

        // Tự động khôi phục c_user từ UID nếu chưa có
        if (!cookieMap.has("c_user")) {
            if (userId && userId !== "0") {
                cookieMap.set("c_user", userId);
            } else if (cookieMap.has("i_user")) {
                cookieMap.set("c_user", cookieMap.get("i_user"));
                userId = cookieMap.get("i_user");
            }
        }

        if (!userId && cookieMap.has("c_user")) {
            userId = cookieMap.get("c_user");
        }

        // Tạo chuỗi Cookie
        let cookiePairs = [];
        for (let [name, val] of cookieMap.entries()) {
            cookiePairs.push(`${name}=${val}`);
        }
        let cookieStr = cookiePairs.join("; ");

        // Kiểm tra hợp lệ
        if (!fb_dtsg && !cookieMap.has("c_user") && !userId) {
            status.innerHTML = "❌ <b>Không trích xuất được thông tin đăng nhập!</b><br><small style='color:#fca5a5'>Vui lòng F5 lại tab Facebook và đảm bảo bạn đã đăng nhập.</small>";
            status.style.color = "#ef4444";
            btn.disabled = false;
            btn.style.opacity = '1';
            return;
        }

        const hasXs = cookieMap.has("xs");
        const hasCUser = cookieMap.has("c_user") || Boolean(userId);
        const userAgent = navigator.userAgent;

        // Gửi qua API của Proxify
        status.innerText = "Đang gửi vào Proxify...";

        const payload = {
            cookie: cookieStr,
            user_agent: userAgent,
            fb_dtsg: fb_dtsg,
            lsd: lsd,
            sd: sd,
            user_id: userId,
            cookie_names: Array.from(cookieMap.keys())
        };

        let success = false;
        try {
            const res = await fetch("http://127.0.0.1:8888/api/facebook/cookie", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (data.status === "ok") success = true;
        } catch (e) {
            try {
                const res = await fetch("http://localhost:8888/api/facebook/cookie", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                const data = await res.json();
                if (data.status === "ok") success = true;
            } catch (err) { }
        }

        if (success) {
            let infoMsg = `✅ <b>ĐỒNG BỘ THÀNH CÔNG!</b><br>`;
            infoMsg += `<small style="color:#a7f3d0">UID: <b>${userId || 'Đã nhận'}</b> | Token: <b>${fb_dtsg ? fb_dtsg.slice(0, 10) + '...' : 'Đã nạp'}</b></small><br><br>`;
            infoMsg += `<span style="font-size:11px;color:#94a3b8">💡 <b>Tiếp theo:</b> Mở Dashboard Proxify (cổng 8888) và bấm <b>Bắt đầu thu thập</b> để hệ thống chạy trực tiếp qua Tab Facebook!</span>`;
            status.innerHTML = infoMsg;
            status.style.color = "#10b981";
        } else {
            status.innerHTML = "❌ <b>Lỗi kết nối Proxify!</b><br><small style='color:#fca5a5'>Hãy đảm bảo backend đang chạy ở port 8888.</small>";
            status.style.color = "#ef4444";
        }

    } catch (e) {
        status.innerText = "❌ Lỗi xử lý Extension: " + e.message;
        status.style.color = "#ef4444";
        console.error(e);
    }

    btn.disabled = false;
    btn.style.opacity = '1';
});
