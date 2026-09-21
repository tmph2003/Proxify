// =============================================================================
// Proxify — YouTube Anti-AFK Content Script
// =============================================================================
// Prevents YouTube's "Video đã tạm dừng. Tiếp tục xem?" (Video paused.
// Continue watching?) idle detection popup from interrupting playback.
//
// Strategy: Defense-in-Depth with 2 layers
//   Layer 1 (Proactive):  Activity Simulator — periodically dispatches
//                          mousemove events to reset YouTube's internal
//                          LACT (Last Activity Timestamp) counter.
//   Layer 2 (Reactive):   MutationObserver — auto-dismisses the confirm
//                          dialog if it still appears, then resumes video.
//
// Architecture: This runs as a Chrome Extension Content Script, which is
// exempt from the page's CSP (Content Security Policy). This is the correct
// architectural layer for DOM manipulation — the proxy layer handles
// Transport & Data Filtering only.
// =============================================================================

(function () {
    "use strict";

    const TAG = "[Proxify Anti-AFK]";
    const ACTIVITY_INTERVAL_MS = 60_000;       // Dispatch mousemove every 60s
    const OBSERVER_DEBOUNCE_MS = 300;          // Debounce observer checks
    const RESUME_DELAY_MS = 500;               // Delay before resuming video after dismiss

    let observerActive = false;
    let activityTimerId = null;
    let observer = null;

    // =========================================================================
    // Layer 1: Activity Simulator (Proactive Prevention)
    // =========================================================================
    // YouTube's player tracks user activity via DOM event listeners on the
    // document (mousemove, keydown, scroll, touchstart, etc.). When no events
    // are received for ~30-60 minutes, it triggers the AFK popup.
    //
    // By dispatching a synthetic mousemove event periodically, we keep the
    // LACT counter fresh and prevent the popup from ever appearing.
    // =========================================================================

    function simulateActivity() {
        try {
            // Dispatch mousemove on document — this is what YouTube's player
            // listens to for activity tracking
            document.dispatchEvent(new MouseEvent("mousemove", {
                bubbles: true,
                cancelable: true,
                clientX: Math.floor(Math.random() * 200) + 100,
                clientY: Math.floor(Math.random() * 200) + 100,
            }));

            // Also dispatch on the video player container for redundancy
            const player = document.getElementById("movie_player");
            if (player) {
                player.dispatchEvent(new MouseEvent("mousemove", {
                    bubbles: true,
                    cancelable: true,
                    clientX: Math.floor(Math.random() * 200) + 100,
                    clientY: Math.floor(Math.random() * 200) + 100,
                }));
            }
        } catch (e) {
            // Silent — never break the page
        }
    }

    function startActivitySimulator() {
        if (activityTimerId) return;
        activityTimerId = setInterval(simulateActivity, ACTIVITY_INTERVAL_MS);
        console.log(`${TAG} Activity simulator started (interval: ${ACTIVITY_INTERVAL_MS / 1000}s)`);
    }

    function stopActivitySimulator() {
        if (activityTimerId) {
            clearInterval(activityTimerId);
            activityTimerId = null;
        }
    }

    // =========================================================================
    // Layer 2: MutationObserver — Auto-dismiss AFK Popup (Reactive Fallback)
    // =========================================================================
    // If the popup still appears despite the activity simulator (e.g., YouTube
    // changes their detection mechanism), this observer catches it and
    // automatically clicks the confirm button.
    //
    // Known popup DOM structures:
    //   - <yt-confirm-dialog-renderer> containing a confirm button
    //   - <tp-yt-paper-dialog> wrapping the confirm dialog
    //   - The confirm button can be:
    //     * #confirm-button inside yt-confirm-dialog-renderer
    //     * a.yt-simple-endpoint with text "Có" / "Yes" / "OK"
    //     * yt-button-renderer#confirm-button
    // =========================================================================

    // Multiple selectors for resilience against YouTube DOM changes
    const POPUP_SELECTORS = [
        "yt-confirm-dialog-renderer",
        "tp-yt-paper-dialog.ytd-popup-container",
        ".yt-confirm-dialog-renderer",
    ];

    const CONFIRM_BUTTON_SELECTORS = [
        // Primary: the confirm button inside the dialog
        "yt-confirm-dialog-renderer #confirm-button",
        "yt-confirm-dialog-renderer yt-button-renderer#confirm-button",
        // Secondary: paper-dialog buttons
        "tp-yt-paper-dialog #confirm-button",
        "tp-yt-paper-dialog .yt-spec-button-shape-next",
        // Tertiary: generic button inside popup container
        "ytd-popup-container #confirm-button",
        "ytd-popup-container yt-button-renderer a.yt-simple-endpoint",
    ];

    function tryDismissPopup() {
        // Check if a confirm dialog is actually visible
        let popupFound = false;
        for (const sel of POPUP_SELECTORS) {
            const popup = document.querySelector(sel);
            if (popup && popup.offsetParent !== null) {
                popupFound = true;
                break;
            }
            // Some YouTube elements use shadow DOM — check visibility via style
            if (popup && !popup.hidden && getComputedStyle(popup).display !== "none") {
                popupFound = true;
                break;
            }
        }

        if (!popupFound) return false;

        console.log(`${TAG} AFK popup detected! Attempting auto-dismiss...`);

        // Try clicking the confirm button
        for (const sel of CONFIRM_BUTTON_SELECTORS) {
            const btn = document.querySelector(sel);
            if (btn) {
                // Some buttons are <a> tags, some are <button> inside custom elements
                const clickTarget = btn.querySelector("button") ||
                                    btn.querySelector("a") ||
                                    btn;
                if (clickTarget) {
                    clickTarget.click();
                    console.log(`${TAG} Clicked confirm button via: ${sel}`);

                    // Resume video after a short delay
                    setTimeout(resumeVideo, RESUME_DELAY_MS);
                    return true;
                }
            }
        }

        // Fallback: try to find any button with "Có", "Yes", or "OK" text
        const allButtons = document.querySelectorAll(
            "tp-yt-paper-dialog button, " +
            "yt-confirm-dialog-renderer button, " +
            "ytd-popup-container button, " +
            "tp-yt-paper-dialog a, " +
            "yt-confirm-dialog-renderer a"
        );
        for (const btn of allButtons) {
            const text = (btn.textContent || "").trim().toLowerCase();
            if (text === "có" || text === "yes" || text === "ok" ||
                text === "continue watching" || text === "tiếp tục xem") {
                btn.click();
                console.log(`${TAG} Clicked button by text match: "${text}"`);
                setTimeout(resumeVideo, RESUME_DELAY_MS);
                return true;
            }
        }

        console.warn(`${TAG} Popup detected but no confirm button found!`);
        return false;
    }

    function resumeVideo() {
        try {
            const video = document.querySelector("video.html5-main-video") ||
                          document.querySelector("video");
            if (video && video.paused) {
                video.play().then(() => {
                    console.log(`${TAG} Video resumed successfully`);
                }).catch(() => {
                    // Some browsers require user gesture — try clicking the player
                    const playButton = document.querySelector(".ytp-play-button");
                    if (playButton) playButton.click();
                });
            }
        } catch (e) {
            // Silent
        }
    }

    // =========================================================================
    // Observer Setup
    // =========================================================================

    let debounceTimer = null;

    function onDomMutation() {
        // Debounce to avoid excessive checks during rapid DOM changes
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            tryDismissPopup();
        }, OBSERVER_DEBOUNCE_MS);
    }

    function startObserver() {
        if (observerActive) return;

        // Watch the popup container where YouTube injects dialogs
        const target = document.querySelector("ytd-popup-container") || document.body;

        observer = new MutationObserver(onDomMutation);
        observer.observe(target, {
            childList: true,
            subtree: true,
        });

        observerActive = true;
        console.log(`${TAG} DOM observer started on: ${target.tagName}${target.id ? "#" + target.id : ""}`);
    }

    function stopObserver() {
        if (observer) {
            observer.disconnect();
            observer = null;
            observerActive = false;
        }
    }

    // =========================================================================
    // SPA Navigation Handler
    // =========================================================================
    // YouTube is a Single Page Application — when navigating between videos,
    // the page doesn't fully reload. We need to listen for YouTube's custom
    // navigation events to re-initialize our observers.
    // =========================================================================

    function init() {
        startActivitySimulator();
        startObserver();
        console.log(`${TAG} Initialized — activity simulator + DOM observer active`);
    }

    // YouTube fires 'yt-navigate-finish' after SPA navigation completes
    document.addEventListener("yt-navigate-finish", () => {
        console.log(`${TAG} SPA navigation detected — re-initializing observer`);
        stopObserver();
        // Short delay to let YouTube finish rendering
        setTimeout(() => {
            startObserver();
        }, 1000);
    });

    // Also handle page visibility changes — when tab becomes visible again,
    // ensure everything is still running
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            if (!activityTimerId) startActivitySimulator();
            if (!observerActive) startObserver();
        }
    });

    // =========================================================================
    // Bootstrap
    // =========================================================================

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
