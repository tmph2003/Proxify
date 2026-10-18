// ==========================================
// CONFIGURATION HELPER
// ==========================================
const DEFAULT_BYPASS_LIST = [
    "localhost",
    "127.0.0.1",
    "<local>",
    "192.168.*",
    "10.*",
    "172.16.*",
    "accounts.google.com"
];

async function getExtensionConfig() {
    return new Promise(resolve => {
        if (chrome.storage && chrome.storage.local) {
            chrome.storage.local.get(
                {
                    serverUrl: "http://127.0.0.1:8888",
                    bypassList: DEFAULT_BYPASS_LIST
                },
                (items) => {
                    let sUrl = (items.serverUrl || "http://127.0.0.1:8888").trim().replace(/\/+$/, "");
                    let bList = Array.isArray(items.bypassList) ? items.bypassList : DEFAULT_BYPASS_LIST;
                    resolve({ serverUrl: sUrl, bypassList: bList });
                }
            );
        } else {
            resolve({ serverUrl: "http://127.0.0.1:8888", bypassList: DEFAULT_BYPASS_LIST });
        }
    });
}

// ==========================================
// PROXY CONTROLLER & BADGE INDICATOR
// ==========================================
function updateProxyBadge(isActive) {
    if (!chrome.action) return;
    if (isActive) {
        chrome.action.setBadgeText({ text: "ON" });
        chrome.action.setBadgeBackgroundColor({ color: "#10b981" });
    } else {
        chrome.action.setBadgeText({ text: "" });
    }
}

function syncProxyBadgeStatus() {
    if (!chrome.proxy || !chrome.proxy.settings) return;
    chrome.proxy.settings.get({ incognito: false }, (details) => {
        if (!details || !details.value) return;
        const isFixed = details.value.mode === "fixed_servers";
        updateProxyBadge(isFixed);
    });
}

if (chrome.proxy && chrome.proxy.settings) {
    syncProxyBadgeStatus();
    chrome.proxy.settings.onChange.addListener((details) => {
        if (details && details.value) {
            updateProxyBadge(details.value.mode === "fixed_servers");
        }
    });
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "SET_PROXY_MODE") {
        if (!chrome.proxy || !chrome.proxy.settings) {
            sendResponse({ ok: false, error: "Thiếu quyền 'proxy' trong Extension. Hãy bấm Reload tiện ích trong chrome://extensions" });
            return false;
        }
        if (msg.enable) {
            const host = msg.host || "127.0.0.1";
            const port = parseInt(msg.port || 8080, 10);
            getExtensionConfig().then(cfg => {
                chrome.proxy.settings.set(
                    {
                        value: {
                            mode: "fixed_servers",
                            rules: {
                                singleProxy: { scheme: "http", host: host, port: port },
                                bypassList: cfg.bypassList
                            }
                        },
                        scope: "regular"
                    },
                    () => {
                        syncProxyBadgeStatus();
                        sendResponse({ ok: true, enabled: true });
                    }
                );
            });
        } else {
            chrome.proxy.settings.clear({ scope: "regular" }, () => {
                syncProxyBadgeStatus();
                sendResponse({ ok: true, enabled: false });
            });
        }
        return true;
    }
});
