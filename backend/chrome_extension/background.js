let pendingGraphQLRequests = {};

chrome.webRequest.onBeforeRequest.addListener(
    (details) => {
        if (details.method !== "POST" || !details.url.includes("/api/graphql")) return;

        let formData = {};
        if (details.requestBody) {
            if (details.requestBody.formData) {
                for (let key in details.requestBody.formData) {
                    formData[key] = details.requestBody.formData[key][0];
                }
            } else if (details.requestBody.raw && details.requestBody.raw.length > 0) {
                try {
                    let decoder = new TextDecoder("utf-8");
                    let rawStr = "";
                    for (let part of details.requestBody.raw) {
                        if (part.bytes) {
                            rawStr += decoder.decode(part.bytes, { stream: true });
                        }
                    }
                    if (rawStr) {
                        if (rawStr.includes("Content-Disposition: form-data;")) {
                            let regex = /Content-Disposition:\s*form-data;\s*name="([^"]+)"(?:;\s*filename="[^"]*")?(?:\r?\nContent-Type:[^\r\n]*)?\r?\n\r?\n([\s\S]*?)(?=\r?\n--|$)/g;
                            let m;
                            while ((m = regex.exec(rawStr)) !== null) {
                                formData[m[1]] = m[2];
                            }
                        } else {
                            let params = new URLSearchParams(rawStr);
                            for (let [key, val] of params.entries()) {
                                formData[key] = val;
                            }
                        }
                    }
                } catch (e) {
                    console.error("[Proxify] Error parsing raw request body:", e);
                }
            }
        }

        let friendlyName = formData["fb_api_req_friendly_name"] || "";
        if (!friendlyName && details.url.includes("fb_api_req_friendly_name=")) {
            try {
                let u = new URL(details.url);
                friendlyName = u.searchParams.get("fb_api_req_friendly_name") || "";
            } catch (e) { }
        }
        if (!friendlyName && formData["doc_id"]) {
            friendlyName = "GraphQL_doc_" + formData["doc_id"];
        }

        if (friendlyName) {
            let isTarget = friendlyName.includes("Group") || 
                           friendlyName.includes("Feed") || 
                           friendlyName.includes("Comment") || 
                           friendlyName.includes("UFI") ||
                           friendlyName.includes("Story") ||
                           friendlyName.includes("Post") ||
                           friendlyName.includes("GraphQL");
            if (isTarget) {
                pendingGraphQLRequests[details.requestId] = {
                    form_data: formData,
                    friendly_name: friendlyName
                };
                console.log(`[Proxify] Intercepted GraphQL Request: ${friendlyName} (ReqId: ${details.requestId})`);
            }
        }
    },
    { urls: ["*://*.facebook.com/api/graphql*", "*://facebook.com/api/graphql*"] },
    ["requestBody"]
);

chrome.webRequest.onBeforeSendHeaders.addListener(
    (details) => {
        if (pendingGraphQLRequests[details.requestId]) {
            let reqData = pendingGraphQLRequests[details.requestId];
            let headers = {};
            
            // Extract headers
            details.requestHeaders.forEach(h => {
                let k = h.name.toLowerCase();
                // Skip pseudo-headers and connection-specific headers
                let skipHeaders = ["content-length", "accept-encoding", "host", "connection"];
                if (k.startsWith(":") || skipHeaders.includes(k)) return;
                
                if (headers[k]) {
                    headers[k] += "; " + h.value;
                } else {
                    headers[k] = h.value;
                }
            });

            let friendlyName = reqData.friendly_name;
            let template = {
                headers: headers,
                form_data: reqData.form_data
            };
            
            console.log(`[Proxify] Captured full template for ${friendlyName}! Sending to backend...`);

            // Send to Proxify server silently with client_id
            getExtensionConfig().then(cfg => {
                fetch(`${cfg.serverUrl}/api/facebook/cookie`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ feed_template: template, friendly_name: friendlyName, client_id: cfg.clientId })
                }).then(res => res.json())
                  .then(data => console.log(`[Proxify] Backend acknowledged ${friendlyName} (${cfg.clientId}):`, data))
                  .catch(e => {
                      if (cfg.serverUrl.includes("127.0.0.1")) {
                          fetch("http://localhost:8888/api/facebook/cookie", {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({ feed_template: template, friendly_name: friendlyName, client_id: cfg.clientId })
                          }).catch(err => {});
                      }
                  });
            });

            delete pendingGraphQLRequests[details.requestId];
        }
    },
    { urls: ["*://*.facebook.com/api/graphql*", "*://facebook.com/api/graphql*"] },
    ["requestHeaders", "extraHeaders"]
);

// Cleanup maps to prevent memory leaks if requests fail or complete before headers are sent
chrome.webRequest.onCompleted.addListener((details) => { delete pendingGraphQLRequests[details.requestId]; }, { urls: ["*://*.facebook.com/api/graphql*", "*://facebook.com/api/graphql*"] });
chrome.webRequest.onErrorOccurred.addListener((details) => { delete pendingGraphQLRequests[details.requestId]; }, { urls: ["*://*.facebook.com/api/graphql*", "*://facebook.com/api/graphql*"] });

// ==========================================
// CONFIGURATION HELPER (Multi-Client)
// ==========================================
async function getExtensionConfig() {
    return new Promise(resolve => {
        if (chrome.storage && chrome.storage.local) {
            chrome.storage.local.get({ serverUrl: "http://127.0.0.1:8888", clientId: "default" }, (items) => {
                let sUrl = (items.serverUrl || "http://127.0.0.1:8888").trim().replace(/\/+$/, "");
                let cId = (items.clientId || "default").trim() || "default";
                resolve({ serverUrl: sUrl, clientId: cId });
            });
        } else {
            resolve({ serverUrl: "http://127.0.0.1:8888", clientId: "default" });
        }
    });
}

// Alarms to ensure service worker stays awake
chrome.alarms.create("bridge_poll_keepalive", { periodInMinutes: 0.2 });
chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === "bridge_poll_keepalive") {
        pollForBridgeJobs();
    }
});

// Listen for keep-alive pings from content scripts in Facebook tabs
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "KEEPALIVE") {
        sendResponse({ status: "alive" });
    }
});

let lastCookieSyncTime = 0;

async function syncFacebookCookies(serverUrl, clientId) {
    const now = Date.now();
    if (now - lastCookieSyncTime < 15000) return;
    lastCookieSyncTime = now;

    try {
        let cookieMap = new Map();
        const domains = [".facebook.com", "facebook.com", "www.facebook.com"];
        for (const dom of domains) {
            try {
                const unpart = await chrome.cookies.getAll({ domain: dom });
                unpart.forEach(c => cookieMap.set(c.name, c.value));
            } catch (e) {}
            try {
                const part = await chrome.cookies.getAll({ domain: dom, partitionKey: {} });
                part.forEach(c => cookieMap.set(c.name, c.value));
            } catch (e) {}
        }

        const cookiePairs = [];
        cookieMap.forEach((v, k) => cookiePairs.push(`${k}=${v}`));
        const cookieString = cookiePairs.join("; ");
        const names = Array.from(cookieMap.keys());

        if (cookieMap.has("c_user") || names.length > 0) {
            await fetch(`${serverUrl}/api/facebook/cookie`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    cookie: cookieString,
                    user_id: cookieMap.get("c_user") || "",
                    user_agent: navigator.userAgent,
                    cookie_names: names,
                    client_id: clientId
                })
            });
        }
    } catch (e) {
        // silent
    }
}

let isPolling = false;
let isExecutingJob = false;
async function pollForBridgeJobs() {
    if (isPolling || isExecutingJob) return;
    isPolling = true;
    try {
        const cfg = await getExtensionConfig();
        await syncFacebookCookies(cfg.serverUrl, cfg.clientId);
        
        let res = await fetch(`${cfg.serverUrl}/api/facebook/bridge/jobs?client_id=${encodeURIComponent(cfg.clientId)}`);
        if (res.ok) {
            let data = await res.json();
            if (data.job) {
                console.log(`[Proxify Bridge] Received job ${data.job.id} for client: ${cfg.clientId}`);
                isExecutingJob = true;
                executeBridgeJob(data.job, cfg.serverUrl, cfg.clientId).finally(() => {
                    isExecutingJob = false;
                });
            }
        }
    } catch (e) {
        // Silent fail on connection error
    } finally {
        isPolling = false;
    }
    
    // Loop
    setTimeout(pollForBridgeJobs, 1000);
}

async function executeBridgeJob(job, serverUrl, clientId) {
    try {
        let text = "";
        let statusCode = 200;
        let executedInTab = false;

        // ƯU TIÊN 1: Thực thi bên trong Tab Facebook thật trong MAIN world
        let targetTabInfo = null;
        let tabError = null;
        try {
            const allTabs = await chrome.tabs.query({});
            let fbTabs = allTabs.filter(t => t.url && (t.url.includes("facebook.com") || t.url.includes("fb.com")));
            
            // Ưu tiên tab không bị Chrome Memory Saver discard
            let candidates = fbTabs.filter(t => !t.discarded);
            if (candidates.length === 0) candidates = fbTabs;

            let targetTab = null;
            const targetUrl = job.target_group_url;

            if (targetUrl) {
                // Kiểm tra xem đã có tab nào đang mở đúng URL nhóm chưa
                try {
                    const urlObj = new URL(targetUrl);
                    const path = urlObj.pathname;
                    targetTab = candidates.find(t => t.url && t.url.includes(path));
                } catch(e) {}
            }

            if (!targetTab) {
                targetTab = candidates.find(t => t.active) || candidates[0];
            }

            if (!targetTab) {
                console.log("[Proxify Bridge] Không thấy tab Facebook nào đang mở! Tự động tạo tab Facebook ngầm...");
                const openUrl = targetUrl || "https://www.facebook.com";
                targetTab = await chrome.tabs.create({ url: openUrl, active: false });
                await new Promise(r => setTimeout(r, 5000));
            }

            if (targetTab) {
                targetTabInfo = { id: targetTab.id, url: targetTab.url };
                
                const results = await chrome.scripting.executeScript({
                    target: { tabId: targetTab.id },
                    world: "MAIN",
                    args: [job.url, job.method || "POST", job.headers || {}, job.body],
                    func: async (url, method, headers, body) => {
                        try {
                            // GUARDRAIL: Chỉ cho phép /api/graphql/ bên trong tab để bảo vệ an toàn tài khoản
                            if (!url || !url.includes("/api/graphql")) {
                                console.error("[Proxify Bridge] TỪ CHỐI thực thi request không phải GraphQL bên trong tab:", url);
                                return {
                                    status_code: 403,
                                    text: "Rejected: In-tab execution strictly permits /api/graphql/ endpoints only.",
                                    executed_in_tab: true,
                                    tab_url: window.location.href,
                                    tab_error: "Non-GraphQL request rejected for account safety."
                                };
                            }

                            // 1. Trích xuất token bảo mật LIVE trực tiếp từ trang Facebook đang mở
                            let liveDtsg = null;
                            let liveUserId = null;
                            let liveLsd = null;
                            
                            try {
                                if (window.require) {
                                    try { liveDtsg = window.require("DTSGInitialData")?.token; } catch(e){}
                                    if (!liveDtsg) {
                                        try { liveDtsg = window.require("DTSG")?.getToken?.(); } catch(e){}
                                    }
                                    try { liveUserId = window.require("CurrentUserInitialData")?.USER_ID || window.require("CurrentUserInitialData")?.ACCOUNT_ID; } catch(e){}
                                    try { liveLsd = window.require("LSD")?.token; } catch(e){}
                                }
                            } catch(e) {}
                            
                            if (!liveDtsg) {
                                const input = document.querySelector('input[name="fb_dtsg"]');
                                if (input) liveDtsg = input.value;
                            }
                            if (!liveDtsg) {
                                const html = document.documentElement.innerHTML;
                                const m = html.match(/"DTSGInitialData",\[\],\{"token":"([^"]+)"/);
                                if (m) liveDtsg = m[1];
                            }
                            if (!liveUserId) {
                                const html = document.documentElement.innerHTML;
                                const m = html.match(/"USER_ID":"(\d+)"/);
                                if (m) liveUserId = m[1];
                            }
                            if (!liveLsd) {
                                const input = document.querySelector('input[name="lsd"]');
                                if (input) liveLsd = input.value;
                            }

                            // 2. Bổ sung token LIVE vào body nếu body chưa có hoặc thiếu token (bảo toàn tính nhất quán)
                            let updatedBody = body;
                            if (typeof updatedBody === "string" && updatedBody) {
                                if (liveDtsg && (!updatedBody.includes("fb_dtsg=") || updatedBody.includes("fb_dtsg=&") || updatedBody.endsWith("fb_dtsg="))) {
                                    const liveJazoest = "2" + liveDtsg.split('').reduce((sum, c) => sum + c.charCodeAt(0), 0);
                                    updatedBody = `${updatedBody}&fb_dtsg=${encodeURIComponent(liveDtsg)}&jazoest=${liveJazoest}`;
                                }
                                if (liveUserId && (!updatedBody.includes("__user=") || updatedBody.includes("__user=&") || updatedBody.endsWith("__user="))) {
                                    updatedBody = `${updatedBody}&__user=${liveUserId}&av=${liveUserId}`;
                                }
                                if (liveLsd && (!updatedBody.includes("lsd=") || updatedBody.includes("lsd=&") || updatedBody.endsWith("lsd="))) {
                                    updatedBody = `${updatedBody}&lsd=${encodeURIComponent(liveLsd)}`;
                                }
                            }
                            if (headers && liveLsd && !headers["x-fb-lsd"]) {
                                headers["x-fb-lsd"] = liveLsd;
                            }

                            // 4. Thực thi fetch trong context của tab với timeout an toàn
                            const fetchOptions = {
                                method: method,
                                headers: Object.assign({}, headers),
                                credentials: "include"
                            };
                            const isGetOrHead = method.toUpperCase() === "GET" || method.toUpperCase() === "HEAD";
                            if (!isGetOrHead && updatedBody) {
                                fetchOptions.body = updatedBody;
                                if (!fetchOptions.headers["Content-Type"] && !fetchOptions.headers["content-type"]) {
                                    fetchOptions.headers["Content-Type"] = "application/x-www-form-urlencoded";
                                }
                            }

                            const controller = new AbortController();
                            const timeoutId = setTimeout(() => controller.abort(), 60000);
                            fetchOptions.signal = controller.signal;

                            let res;
                            let t = "";
                            try {
                                res = await fetch(url, fetchOptions);
                                clearTimeout(timeoutId);
                                t = await res.text();
                            } catch (fetchErr) {
                                clearTimeout(timeoutId);
                                throw fetchErr;
                            }

                            // 5. CƠ CHẾ DỰ PHÒNG CÀO DOM (DOM Scraper Fallback) nếu GraphQL trả về lỗi 1357001
                            if (t.includes("1357001") || res.status !== 200) {
                                console.log("[Proxify Tab] GraphQL báo lỗi, tự động kích hoạt cào trực tiếp từ DOM...");
                                const articles = document.querySelectorAll('div[role="feed"] div[role="article"], div[data-ad-preview="message"]');
                                const domStories = [];
                                
                                articles.forEach((art, idx) => {
                                    const msgEl = art.querySelector('div[data-ad-preview="message"]') || art.querySelector('div[dir="auto"]');
                                    const text = msgEl ? msgEl.innerText.trim() : "";
                                    
                                    const link = art.querySelector('a[href*="/posts/"], a[href*="/permalink/"]');
                                    const pUrl = link ? link.href : "";
                                    let pid = "";
                                    if (pUrl) {
                                        const m = pUrl.match(/(?:posts|permalink)\/(\d+)/);
                                        if (m) pid = m[1];
                                    }
                                    if (!pid) pid = "dom_post_" + Date.now() + "_" + idx;

                                    const authorEl = art.querySelector('h2 strong, h3 strong, a[role="link"] strong');
                                    const authorName = authorEl ? authorEl.innerText.trim() : "Thành viên Facebook";

                                    if (text || pUrl) {
                                        domStories.push({
                                            "__typename": "Story",
                                            "id": pid,
                                            "post_id": pid,
                                            "url": pUrl,
                                            "creation_time": Math.floor(Date.now() / 1000),
                                            "actors": [{"id": "", "name": authorName}],
                                            "message": {"text": text}
                                        });
                                    }
                                });

                                if (domStories.length > 0) {
                                    console.log(`[Proxify Tab] Đã trích xuất thành công ${domStories.length} bài viết từ DOM giao diện!`);
                                    t = JSON.stringify({
                                        "data": {
                                            "node": {
                                                "group_feed": {
                                                    "edges": domStories.map(s => ({ "node": s }))
                                                }
                                            }
                                        }
                                    });
                                    return {
                                        status_code: 200,
                                        text: t,
                                        from_dom: true,
                                        used_live_dtsg: true
                                    };
                                }
                            }

                            return { 
                                status_code: res.status, 
                                text: t,
                                used_live_dtsg: Boolean(liveDtsg),
                                live_uid: liveUserId
                            };
                        } catch (err) {
                            return { status_code: 0, text: "Tab fetch error: " + err.message };
                        }
                    }
                });

                if (results && results[0] && results[0].result && results[0].result.status_code > 0) {
                    statusCode = results[0].result.status_code;
                    text = results[0].result.text;
                    executedInTab = true;
                    console.log(`[Proxify Bridge] Thực thi trong Tab Facebook ID ${targetTab.id} (${targetTab.url}) thành công! (Status: ${statusCode}, Len: ${text.length}, LiveDtsg: ${results[0].result.used_live_dtsg})`);
                } else if (results && results[0] && results[0].result) {
                    tabError = results[0].result.text;
                }
            } else {
                tabError = "No Facebook tabs available and failed to create one";
            }
        } catch (tabErr) {
            tabError = tabErr.message;
            console.warn("[Proxify Bridge] Lỗi thực thi qua Tab:", tabErr);
        }

        // BẢO VỆ AN TOÀN: Tuyệt đối KHÔNG fallback qua Service Worker fetch để tránh rò rỉ Origin chrome-extension://
        if (!executedInTab) {
            console.error(`[Proxify Bridge] Không có tab Facebook nào khả dụng để thực thi job ${job.id}. Từ chối gửi từ Service Worker để tránh vi phạm bot detection.`);
            statusCode = 0;
            text = JSON.stringify({
                status: "error",
                message: "Không tìm thấy tab Facebook đang mở trong Chrome. Vui lòng mở 1 tab Facebook (facebook.com) và thử lại."
            });
            tabError = tabError || "Không tìm thấy tab Facebook đang hoạt động.";
        }
        
        let result = {
            status_code: statusCode,
            text: text,
            executed_in_tab: executedInTab,
            tab_id: targetTabInfo ? targetTabInfo.id : null,
            tab_url: targetTabInfo ? targetTabInfo.url : null,
            tab_error: tabError
        };
        
        // Gửi kết quả về Proxify
        const sendRes = await fetch(`${serverUrl}/api/facebook/bridge/result`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: job.id, client_id: clientId, result: result })
        });
        if (!sendRes.ok) {
            console.error(`[Proxify Bridge] Lỗi HTTP ${sendRes.status} khi gửi kết quả job ${job.id} về backend:`, await sendRes.text());
        }
        console.log(`[Proxify Bridge] Hoàn tất job ${job.id} cho client ${clientId} (Status: ${statusCode}, Len: ${text.length}, InTab: ${executedInTab})`);
    } catch (e) {
        console.error(`[Proxify Bridge] Job ${job.id} thất bại:`, e);
        try {
            await fetch(`${serverUrl}/api/facebook/bridge/result`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ id: job.id, client_id: clientId, result: { status_code: 0, text: "Fetch failed: " + e.message, executed_in_tab: false, tab_error: e.message } })
            });
        } catch(postErr) {}
    }
}

// Start polling
console.log("[Proxify Bridge] Started polling...");
pollForBridgeJobs();
