let pendingGraphQLRequests = {};

chrome.webRequest.onBeforeRequest.addListener(
    (details) => {
        if (details.method !== "POST" || !details.url.includes("/api/graphql/")) return;

        let formData = {};
        if (details.requestBody && details.requestBody.formData) {
            for (let key in details.requestBody.formData) {
                formData[key] = details.requestBody.formData[key][0];
            }
        }

        if (formData["fb_api_req_friendly_name"]) {
            let friendlyName = formData["fb_api_req_friendly_name"];
            // Intercept Group Feed and Comments queries
            if (friendlyName.includes("GroupsCometFeed") || 
                friendlyName.includes("CometGroup") || 
                friendlyName.includes("Comment") || 
                friendlyName.includes("UFI")) {
                pendingGraphQLRequests[details.requestId] = {
                    form_data: formData,
                    friendly_name: friendlyName
                };
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
                headers[k] = h.value;
            });

            let friendlyName = reqData.friendly_name;
            let template = {
                headers: headers,
                form_data: reqData.form_data
            };
            
            console.log(`[Proxify] Captured ${friendlyName} template!`);

            // Send to Proxify server silently
            fetch("http://localhost:8888/api/facebook/cookie", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ feed_template: template, friendly_name: friendlyName })
            }).then(res => res.json())
              .then(data => console.log(`[Proxify] Sent ${friendlyName}:`, data))
              .catch(e => console.error("[Proxify] Error sending template to server:", e));

            delete pendingGraphQLRequests[details.requestId];
        }
    },
    { urls: ["*://*.facebook.com/api/graphql/*", "*://www.facebook.com/api/graphql/*"] },
    ["requestHeaders", "extraHeaders"]
);

// Cleanup maps to prevent memory leaks if requests fail or complete before headers are sent
chrome.webRequest.onCompleted.addListener((details) => { delete pendingGraphQLRequests[details.requestId]; }, { urls: ["*://*.facebook.com/api/graphql/*"] });
chrome.webRequest.onErrorOccurred.addListener((details) => { delete pendingGraphQLRequests[details.requestId]; }, { urls: ["*://*.facebook.com/api/graphql/*"] });
