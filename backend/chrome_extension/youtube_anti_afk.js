// =============================================================================
// Proxify — YouTube Anti-AFK Content Script v1.2
// =============================================================================
// Prevents YouTube's "Video đã tạm dừng. Tiếp tục xem?" (Video paused.
// Continue watching?) idle detection popup from interrupting playback.
//
// Multi-Tier Strategy:
//   Tier 1 (Proactive Keepalive): Refreshes LACT and dispatches user activity
//                                 events periodically so YouTube never triggers idle.
//   Tier 2 (Continuous Watchdog): Runs a 500ms fast-polling loop to instantly
//                                 detect and click any confirm/resume dialog.
//   Tier 3 (Event-Driven & Mutation): Listens to yt-popup-opened / yt-action events
//                                     and watches DOM mutations including attributes.
// =============================================================================

(function () {
    "use strict";

    const TAG = "[Proxify Anti-AFK]";
    const WATCHDOG_INTERVAL_MS = 500;
    const ACTIVITY_INTERVAL_MS = 15_000;
    const RESUME_DELAY_MS = 250;

    let observer = null;
    let watchdogTimerId = null;
    let activityTimerId = null;

    // =========================================================================
    // Tier 1: Proactive Activity & LACT Keepalive
    // =========================================================================
    function simulateActivity() {
        try {
            // Keep window._lact fresh if accessible
            if (typeof window._lact !== "undefined") {
                window._lact = Date.now();
            }

            // Dispatch mousemove on document and player container
            const coords = {
                bubbles: true,
                cancelable: true,
                clientX: Math.floor(Math.random() * 200) + 100,
                clientY: Math.floor(Math.random() * 200) + 100,
            };
            document.dispatchEvent(new MouseEvent("mousemove", coords));

            const player = document.getElementById("movie_player");
            if (player) {
                player.dispatchEvent(new MouseEvent("mousemove", coords));
            }
        } catch (e) {
            // Silent
        }
    }

    // =========================================================================
    // Tier 2: Dialog Detection & Auto-Dismiss
    // =========================================================================
    const CONFIRM_BUTTON_SELECTORS = [
        "#confirm-button button",
        "#confirm-button .yt-spec-button-shape-next",
        "yt-confirm-dialog-renderer #confirm-button",
        "yt-confirm-dialog-renderer yt-button-shape button",
        "tp-yt-paper-dialog #confirm-button button",
        "tp-yt-paper-dialog #confirm-button",
        "ytd-popup-container #confirm-button button",
        "ytd-popup-container #confirm-button",
        "ytmusic-you-there-renderer #button button",
        "ytmusic-you-there-renderer #button",
    ];

    function clickConfirmTarget(target) {
        if (!target) return false;

        // 1. Check shadowRoot
        if (target.shadowRoot) {
            const innerBtn = target.shadowRoot.querySelector("button");
            if (innerBtn) {
                innerBtn.click();
                return true;
            }
        }

        // 2. Check inner native button
        const nativeBtn = target.querySelector("button") ||
                          target.querySelector("a") ||
                          target;
        if (nativeBtn && typeof nativeBtn.click === "function") {
            nativeBtn.click();
            return true;
        }

        return false;
    }

    function resumeVideo() {
        try {
            const video = document.querySelector("video.html5-main-video") ||
                          document.querySelector("video");
            if (video && video.paused) {
                const playPromise = video.play();
                if (playPromise && playPromise.catch) {
                    playPromise.catch(() => {
                        const player = document.getElementById("movie_player");
                        if (player && typeof player.playVideo === "function") {
                            player.playVideo();
                        } else {
                            const playButton = document.querySelector(".ytp-play-button");
                            if (playButton) playButton.click();
                        }
                    });
                }
                console.log(`${TAG} Video playback resumed`);
            }
        } catch (e) {
            // Silent
        }
    }

    function isElementVisible(el) {
        if (!el) return false;
        if (el.hidden || el.getAttribute("aria-hidden") === "true") return false;
        const style = window.getComputedStyle(el);
        return style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
    }

    function tryDismissPopup() {
        // 1. Check confirm dialog renderers
        const dialogs = document.querySelectorAll(
            "yt-confirm-dialog-renderer, tp-yt-paper-dialog, ytmusic-you-there-renderer, ytd-modal-with-title-and-button-renderer"
        );

        for (const dlg of dialogs) {
            if (!isElementVisible(dlg)) continue;

            const text = (dlg.textContent || "").toLowerCase();
            const isAfkDialog = (
                text.includes("tạm dừng") ||
                text.includes("tiếp tục xem") ||
                text.includes("paused") ||
                text.includes("continue watching") ||
                text.includes("still watching") ||
                dlg.tagName.toLowerCase().includes("you-there")
            );

            if (isAfkDialog) {
                console.log(`${TAG} AFK dialog detected in ${dlg.tagName}! Attempting dismissal...`);

                // Try button selectors inside this dialog first
                for (const sel of CONFIRM_BUTTON_SELECTORS) {
                    const btn = dlg.querySelector(sel);
                    if (btn && clickConfirmTarget(btn)) {
                        console.log(`${TAG} Clicked confirm button via selector: ${sel}`);
                        setTimeout(resumeVideo, RESUME_DELAY_MS);
                        return true;
                    }
                }

                // Fallback: search all buttons in dialog by text
                const buttons = dlg.querySelectorAll("button, a, tp-yt-paper-button");
                for (const b of buttons) {
                    const txt = (b.textContent || "").trim().toLowerCase();
                    const aria = (b.getAttribute("aria-label") || "").trim().toLowerCase();
                    if (
                        txt === "có" || txt === "yes" || txt === "ok" ||
                        txt.includes("tiếp tục") || txt.includes("continue") ||
                        aria === "có" || aria === "yes" || aria.includes("continue")
                    ) {
                        b.click();
                        console.log(`${TAG} Clicked confirm button by text: "${txt || aria}"`);
                        setTimeout(resumeVideo, RESUME_DELAY_MS);
                        return true;
                    }
                }
            }
        }

        // 2. Check opened paper-dialog attribute
        const openedDialog = document.querySelector("tp-yt-paper-dialog[opened]");
        if (openedDialog) {
            const pText = (openedDialog.textContent || "").toLowerCase();
            if (pText.includes("tạm dừng") || pText.includes("paused") || pText.includes("tiếp tục") || pText.includes("continue")) {
                console.log(`${TAG} Opened paper-dialog found: ${pText.slice(0, 40)}`);
                for (const sel of CONFIRM_BUTTON_SELECTORS) {
                    const btn = openedDialog.querySelector(sel);
                    if (btn && clickConfirmTarget(btn)) {
                        setTimeout(resumeVideo, RESUME_DELAY_MS);
                        return true;
                    }
                }
            }
        }

        return false;
    }

    // =========================================================================
    // Tier 3: MutationObserver & Event Listeners
    // =========================================================================
    function startObserver() {
        if (observer) return;

        const target = document.querySelector("ytd-popup-container") || document.body;
        observer = new MutationObserver(() => {
            tryDismissPopup();
        });

        observer.observe(target, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ["opened", "style", "class", "hidden", "aria-hidden"],
        });

        console.log(`${TAG} DOM observer started on: ${target.tagName}`);
    }

    function init() {
        if (!activityTimerId) {
            activityTimerId = setInterval(simulateActivity, ACTIVITY_INTERVAL_MS);
            simulateActivity();
        }

        if (!watchdogTimerId) {
            watchdogTimerId = setInterval(tryDismissPopup, WATCHDOG_INTERVAL_MS);
        }

        startObserver();

        // Native YouTube events
        document.addEventListener("yt-popup-opened", tryDismissPopup);
        document.addEventListener("yt-action", tryDismissPopup);
        document.addEventListener("yt-navigate-finish", () => {
            setTimeout(tryDismissPopup, 500);
            startObserver();
        });

        console.log(`${TAG} Initialized v1.2 (Keepalive + 500ms Watchdog + Observer active)`);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
