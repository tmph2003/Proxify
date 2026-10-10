// Proxify Facebook Tab Content Script
// Runs inside the Facebook web page context: keeps the extension alive and executes in-page GraphQL calls

console.log("[Proxify Content Script] Active on Facebook tab!");

// 1. Keep background service worker permanently awake by pinging every 10 seconds
setInterval(() => {
    try {
        chrome.runtime.sendMessage({ type: "KEEPALIVE" });
    } catch(e) {
        // Ignored if extension reloaded
    }
}, 10000);

// 2. Direct in-page execution listener
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "EXECUTE_IN_PAGE") {
        fetch(request.url, {
            method: request.method || "POST",
            headers: request.headers || {},
            body: request.body,
            credentials: "include"
        })
        .then(async (res) => {
            const text = await res.text();
            sendResponse({ status_code: res.status, text: text });
        })
        .catch((err) => {
            sendResponse({ status_code: 0, text: "Content script fetch error: " + err.message });
        });
        return true; // Keep channel open for async sendResponse
    }
});
