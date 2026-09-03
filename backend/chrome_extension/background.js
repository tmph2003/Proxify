let pendingGraphQLRequests = {};

chrome.webRequest.onBeforeRequest.addListener(
    (details) => {
        if (details.method !== "POST" || !details.url.includes("/api/graphql/")) return;

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
                        let params = new URLSearchParams(rawStr);
                        for (let [key, val] of params.entries()) {
                            formData[key] = val;
                        }
                    }
                } catch (e) {
                    console.error("[Proxify] Error parsing raw request body:", e);
                }
            }
        }

        let friendlyName = formData["fb_api_req_friendly_name"] || "";
        if (friendlyName) {
            let isTarget = friendlyName.includes("Group") || 
                           friendlyName.includes("Feed") || 
                           friendlyName.includes("Comment") || 
                           friendlyName.includes("UFI") ||
                           friendlyName.includes("Story") ||
                           friendlyName.includes("Post");
            if (isTarget) {
                pendingGraphQLRequests[details.requestId] = {
                    form_data: formData,
                    friendly_name: friendlyName
                };
                console.log(`[Proxify] Intercepted GraphQL Request: ${friendlyName} (ReqId: ${details.requestId})`);
            }
        }
    },
    { urls: ["*://*.facebook.com/api/graphql/*", "*://www.facebook.com/api/graphql/*"] },
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

            // Send to Proxify server silently
            fetch("http://127.0.0.1:8888/api/facebook/cookie", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ feed_template: template, friendly_name: friendlyName })
            }).then(res => res.json())
              .then(data => console.log(`[Proxify] Backend acknowledged ${friendlyName}:`, data))
              .catch(e => {
                  fetch("http://localhost:8888/api/facebook/cookie", {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ feed_template: template, friendly_name: friendlyName })
                  }).catch(err => console.error("[Proxify] Error sending template to server:", err));
              });

            delete pendingGraphQLRequests[details.requestId];
        }
    },
    { urls: ["*://*.facebook.com/api/graphql/*", "*://www.facebook.com/api/graphql/*"] },
    ["requestHeaders", "extraHeaders"]
);

// Cleanup maps to prevent memory leaks if requests fail or complete before headers are sent
chrome.webRequest.onCompleted.addListener((details) => { delete pendingGraphQLRequests[details.requestId]; }, { urls: ["*://*.facebook.com/api/graphql/*"] });
chrome.webRequest.onErrorOccurred.addListener((details) => { delete pendingGraphQLRequests[details.requestId]; }, { urls: ["*://*.facebook.com/api/graphql/*"] });

// ==========================================
// EXTENSION BRIDGE: Native Fetch Execution
// ==========================================
const PROXIFY_BRIDGE_JOBS = "http://127.0.0.1:8888/api/facebook/bridge/jobs";
const PROXIFY_BRIDGE_RESULT = "http://127.0.0.1:8888/api/facebook/bridge/result";

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

const PROXIFY_COOKIE_API = "http://127.0.0.1:8888/api/facebook/cookie";
let lastCookieSyncTime = 0;

async function syncFacebookCookies() {
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
            await fetch(PROXIFY_COOKIE_API, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    cookie: cookieString,
                    user_id: cookieMap.get("c_user") || "",
                    user_agent: navigator.userAgent,
                    cookie_names: names
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
        syncFacebookCookies();
        let res = await fetch(PROXIFY_BRIDGE_JOBS);
        if (res.ok) {
            let data = await res.json();
            if (data.job) {
                console.log("[Proxify Bridge] Received job:", data.job.id);
                isExecutingJob = true;
                executeBridgeJob(data.job).finally(() => {
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

async function executeBridgeJob(job) {
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
                            // 1. Kiểm tra quyền xem bài viết trong nhóm trên giao diện
                            const bodyText = document.body ? document.body.innerText : "";
                            const isRestricted = bodyText.includes("Nội dung này hiện không khả dụng") || 
                                                 bodyText.includes("This content isn't available");
                            const hasJoinButton = Boolean(document.querySelector('[aria-label="Tham gia nhóm"], [aria-label="Join group"], [aria-label="Tham gia"]'));

                            if (isRestricted || hasJoinButton) {
                                return {
                                    status_code: 403,
                                    text: JSON.stringify({
                                        error: 1357001,
                                        errorSummary: "Bạn chưa là thành viên của nhóm này",
                                        errorDescription: "Nhóm này là nhóm Riêng tư và tài khoản Facebook hiện tại chưa được duyệt vào nhóm. Vui lòng bấm 'Tham gia nhóm' trên Facebook trước khi thu thập."
                                    })
                                };
                            }

                            // 2. Trích xuất token bảo mật LIVE trực tiếp từ trang Facebook đang mở
                            let liveDtsg = null;
                            let liveUserId = null;
                            let liveLsd = null;
                            
                            try {
                                if (window.require) {
                                    try { liveDtsg = window.require("DTSGInitialData")?.token; } catch(e){}
                                    if (!liveDtsg) {
                                        try { liveDtsg = window.require("DTSG")?.getToken?.(); } catch(e){}
                                    }
                                    try { liveUserId = window.require("CurrentUserInitialData")?.USER_ID; } catch(e){}
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

                            // 3. Cập nhật body với token LIVE (chỉ khi body chưa có token)
                            let updatedBody = body;
                            if (liveDtsg && typeof updatedBody === "string" && !updatedBody.includes("fb_dtsg=")) {
                                const liveJazoest = "2" + liveDtsg.split('').reduce((sum, c) => sum + c.charCodeAt(0), 0);
                                updatedBody = updatedBody ? `${updatedBody}&fb_dtsg=${encodeURIComponent(liveDtsg)}` : `fb_dtsg=${encodeURIComponent(liveDtsg)}`;
                                if (!updatedBody.includes("jazoest=")) {
                                    updatedBody = `${updatedBody}&jazoest=${liveJazoest}`;
                                }
                            }
                            if (liveUserId && typeof updatedBody === "string" && !updatedBody.includes("__user=")) {
                                updatedBody = updatedBody ? `${updatedBody}&__user=${liveUserId}` : `__user=${liveUserId}`;
                                if (!updatedBody.includes("av=")) {
                                    updatedBody = `${updatedBody}&av=${liveUserId}`;
                                }
                            }
                            if (liveLsd && typeof updatedBody === "string" && !updatedBody.includes("lsd=")) {
                                updatedBody = updatedBody ? `${updatedBody}&lsd=${encodeURIComponent(liveLsd)}` : `lsd=${encodeURIComponent(liveLsd)}`;
                            }
                            if (headers && liveLsd) {
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

        // ƯU TIÊN 2: Fallback qua Service Worker fetch nếu không có tab Facebook
        if (!executedInTab) {
            console.log(`[Proxify Bridge] Fallback thực thi qua Service Worker fetch cho job ${job.id}`);
            const method = job.method || "POST";
            let fetchOptions = {
                method: method,
                headers: job.headers || {},
                credentials: "include",
                mode: "cors"
            };
            const isGetOrHead = method.toUpperCase() === "GET" || method.toUpperCase() === "HEAD";
            if (!isGetOrHead && job.body) {
                fetchOptions.body = job.body;
                if (!fetchOptions.headers["Content-Type"] && !fetchOptions.headers["content-type"]) {
                    fetchOptions.headers["Content-Type"] = "application/x-www-form-urlencoded";
                }
            }
            
            let res = await fetch(job.url, fetchOptions);
            text = await res.text();
            statusCode = res.status;
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
        const sendRes = await fetch(PROXIFY_BRIDGE_RESULT, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: job.id, result: result })
        });
        if (!sendRes.ok) {
            console.error(`[Proxify Bridge] Lỗi HTTP ${sendRes.status} khi gửi kết quả job ${job.id} về backend:`, await sendRes.text());
        }
        console.log(`[Proxify Bridge] Hoàn tất job ${job.id} (Status: ${statusCode}, Len: ${text.length}, InTab: ${executedInTab})`);
    } catch (e) {
        console.error(`[Proxify Bridge] Job ${job.id} thất bại:`, e);
        try {
            await fetch(PROXIFY_BRIDGE_RESULT, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ id: job.id, result: { status_code: 0, text: "Fetch failed: " + e.message, executed_in_tab: false, tab_error: e.message } })
            });
        } catch(postErr) {}
    }
}

// Start polling
console.log("[Proxify Bridge] Started polling...");
pollForBridgeJobs();
