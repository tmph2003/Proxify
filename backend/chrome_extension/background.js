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

async function pollForBridgeJobs() {
    try {
        let res = await fetch(PROXIFY_BRIDGE_JOBS);
        if (res.ok) {
            let data = await res.json();
            if (data.job) {
                console.log("[Proxify Bridge] Received job:", data.job.id);
                executeBridgeJob(data.job);
            }
        }
    } catch (e) {
        // Silent fail on connection error
    }
    
    // Loop
    setTimeout(pollForBridgeJobs, 1000);
}

async function executeBridgeJob(job) {
    try {
        let fetchOptions = {
            method: job.method || "POST",
            headers: job.headers || {},
            body: job.body,
            credentials: "include",
            mode: "cors"
        };
        
        let res = await fetch(job.url, fetchOptions);
        let text = await res.text();
        
        let result = {
            status_code: res.status,
            text: text
        };
        
        // Post back to Proxify
        await fetch(PROXIFY_BRIDGE_RESULT, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: job.id, result: result })
        });
        console.log(`[Proxify Bridge] Completed job ${job.id} (Status: ${res.status}, Len: ${text.length})`);
    } catch (e) {
        console.error(`[Proxify Bridge] Job ${job.id} failed:`, e);
        await fetch(PROXIFY_BRIDGE_RESULT, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: job.id, result: { status_code: 0, text: "Fetch failed: " + e.message } })
        });
    }
}

// Start polling
console.log("[Proxify Bridge] Started polling...");
pollForBridgeJobs();
