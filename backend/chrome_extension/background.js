// ==========================================
// CONFIGURATION HELPER & STORAGE
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

const BLOCK_RULE_ID_OFFSET = 10000;

async function getExtensionConfig() {
    if (chrome.storage && chrome.storage.local) {
        const items = await chrome.storage.local.get({
            serverUrl: "http://127.0.0.1:8888",
            bypassList: DEFAULT_BYPASS_LIST,
            blockerEnabled: true,
            blockRules: []
        });
        const sUrl = (items.serverUrl || "http://127.0.0.1:8888").trim().replace(/\/+$/, "");
        const bList = Array.isArray(items.bypassList) ? items.bypassList : DEFAULT_BYPASS_LIST;
        const blockerEnabled = items.blockerEnabled !== false;
        const blockRules = Array.isArray(items.blockRules) ? items.blockRules : [];
        return { serverUrl: sUrl, bypassList: bList, blockerEnabled, blockRules };
    }
    return {
        serverUrl: "http://127.0.0.1:8888",
        bypassList: DEFAULT_BYPASS_LIST,
        blockerEnabled: true,
        blockRules: []
    };
}

// ==========================================
// CUSTOM REQUEST BLOCKER (declarativeNetRequest)
// ==========================================
function normalizePatternToUrlFilter(rawPattern) {
    let p = (rawPattern || "").trim();
    if (!p) return null;

    // Strip non-ASCII characters (declarativeNetRequest urlFilter requires ASCII)
    if (/[^\x00-\x7F]/.test(p)) {
        try {
            if (p.includes("://")) {
                const u = new URL(p);
                p = `${u.protocol}//${u.host}${u.pathname}${u.search}`;
            } else {
                const u = new URL(`http://${p}`);
                p = u.hostname + (u.pathname !== "/" ? u.pathname : "") + u.search;
            }
        } catch (err) {
            p = p.replace(/[^\x00-\x7F]/g, "");
        }
    }

    if (!p) return null;

    // Preserve explicit DNR anchors or wildcard schemes
    if (p.startsWith("||") || p.startsWith("|") || p.includes("://")) {
        return p;
    }

    // Subdomain wildcard shorthand: *.example.com -> ||example.com
    if (p.startsWith("*.")) {
        const rest = p.slice(2);
        return rest ? `||${rest}` : null;
    }

    // Plain domain or domain/path (e.g. "doubleclick.net" or "example.com/ads/*")
    // Anchor at domain boundary with || to avoid accidental substring matches on unrelated hosts
    if (/^[a-zA-Z0-9-]+(\.[a-zA-Z0-9-]+)+(\/.*)?$/.test(p)) {
        return `||${p}`;
    }

    // Path/substring pattern (e.g. "/api/telemetry", "ads/banner")
    return p;
}

function buildDnrRules(blockerEnabled, blockRules) {
    if (!blockerEnabled || !Array.isArray(blockRules)) return [];

    const dnrRules = [];
    let idx = 0;

    for (const rule of blockRules) {
        if (!rule || rule.enabled === false) continue;
        const urlFilter = normalizePatternToUrlFilter(rule.pattern);
        if (!urlFilter) continue;

        idx += 1;
        dnrRules.push({
            id: BLOCK_RULE_ID_OFFSET + idx,
            priority: 1,
            action: { type: "block" },
            condition: {
                urlFilter
            }
        });
    }
    return dnrRules;
}

let isSyncingDnr = false;
let pendingSyncDnr = false;
let lastSyncResult = { ok: true, activeCount: 0 };

async function syncDynamicBlockRules() {
    if (isSyncingDnr) {
        pendingSyncDnr = true;
        return lastSyncResult;
    }
    isSyncingDnr = true;
    try {
        do {
            pendingSyncDnr = false;
            if (!chrome.declarativeNetRequest) {
                lastSyncResult = { ok: false, error: "declarativeNetRequest API unavailable" };
                break;
            }
            try {
                const { blockerEnabled, blockRules } = await getExtensionConfig();
                const existingRules = await chrome.declarativeNetRequest.getDynamicRules();
                const removeRuleIds = existingRules
                    .map(r => r.id)
                    .filter(id => id >= BLOCK_RULE_ID_OFFSET);

                const addRules = buildDnrRules(blockerEnabled, blockRules);

                await chrome.declarativeNetRequest.updateDynamicRules({
                    removeRuleIds,
                    addRules
                });
                await syncProxyBadgeStatus();
                lastSyncResult = { ok: true, activeCount: addRules.length };
            } catch (err) {
                console.error("[Proxify Blocker] Failed to sync DNR rules:", err);
                lastSyncResult = { ok: false, error: err.message || String(err) };
            }
        } while (pendingSyncDnr);
        return lastSyncResult;
    } finally {
        isSyncingDnr = false;
    }
}

// ==========================================
// PROXY CONTROLLER & BADGE INDICATOR
// ==========================================
async function updateExtensionBadge(isProxyActive) {
    if (!chrome.action) return;
    try {
        const { blockerEnabled, blockRules } = await getExtensionConfig();
        const activeBlockCount = blockerEnabled
            ? blockRules.filter(r => r && r.enabled !== false && normalizePatternToUrlFilter(r.pattern)).length
            : 0;

        if (isProxyActive) {
            await chrome.action.setBadgeText({ text: "ON" });
            await chrome.action.setBadgeBackgroundColor({ color: "#10b981" });
        } else if (activeBlockCount > 0) {
            await chrome.action.setBadgeText({ text: String(activeBlockCount) });
            await chrome.action.setBadgeBackgroundColor({ color: "#f59e0b" });
        } else {
            await chrome.action.setBadgeText({ text: "" });
        }
    } catch (err) {
        console.error("[Proxify Badge] Error updating badge:", err);
    }
}

async function syncProxyBadgeStatus() {
    if (!chrome.proxy || !chrome.proxy.settings) {
        await updateExtensionBadge(false);
        return;
    }
    try {
        const details = await new Promise((resolve) => {
            chrome.proxy.settings.get({ incognito: false }, resolve);
        });
        const isFixed = Boolean(details && details.value && details.value.mode === "fixed_servers");
        await updateExtensionBadge(isFixed);
    } catch (err) {
        console.error("[Proxify Proxy] Error reading proxy status:", err);
    }
}

if (chrome.proxy && chrome.proxy.settings) {
    syncProxyBadgeStatus();
    chrome.proxy.settings.onChange.addListener(async (details) => {
        if (details && details.value) {
            await updateExtensionBadge(details.value.mode === "fixed_servers");
        }
    });
}

chrome.runtime.onInstalled.addListener(async () => {
    await syncDynamicBlockRules();
});

chrome.runtime.onStartup.addListener(async () => {
    await syncDynamicBlockRules();
});

if (chrome.storage && chrome.storage.onChanged) {
    chrome.storage.onChanged.addListener(async (changes, areaName) => {
        if (areaName === "local" && (changes.blockerEnabled || changes.blockRules)) {
            await syncDynamicBlockRules();
        }
    });
}

// Initial rule sync when Service Worker wakes up
syncDynamicBlockRules();

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.type === "SET_PROXY_MODE") {
        (async () => {
            if (!chrome.proxy || !chrome.proxy.settings) {
                sendResponse({
                    ok: false,
                    error: "Thiếu quyền 'proxy' trong Extension. Hãy bấm Reload tiện ích trong chrome://extensions"
                });
                return;
            }
            try {
                if (msg.enable) {
                    const host = msg.host || "127.0.0.1";
                    const port = parseInt(msg.port || 8080, 10);
                    const cfg = await getExtensionConfig();
                    await new Promise((resolve) => {
                        chrome.proxy.settings.set(
                            {
                                value: {
                                    mode: "fixed_servers",
                                    rules: {
                                        singleProxy: { scheme: "http", host, port },
                                        bypassList: cfg.bypassList
                                    }
                                },
                                scope: "regular"
                            },
                            resolve
                        );
                    });
                    await syncProxyBadgeStatus();
                    sendResponse({ ok: true, enabled: true });
                } else {
                    await new Promise((resolve) => {
                        chrome.proxy.settings.clear({ scope: "regular" }, resolve);
                    });
                    await syncProxyBadgeStatus();
                    sendResponse({ ok: true, enabled: false });
                }
            } catch (err) {
                sendResponse({ ok: false, error: err.message || String(err) });
            }
        })();
        return true;
    }

    if (msg.type === "SYNC_BLOCK_RULES") {
        (async () => {
            const result = await syncDynamicBlockRules();
            sendResponse(result);
        })();
        return true;
    }

    return false;
});
