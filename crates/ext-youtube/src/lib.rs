use async_trait::async_trait;
use proxify_sdk::{
    BaseExtension, ExtensionContext, FlowResponse, HttpFlow, MutatorInterceptor, RecordFilter,
};
use regex::Regex;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::{Arc, OnceLock};
use tracing::{debug, info};

// Note: Spoofed bait endpoints (ad_status.js, /pagead/id) are handled in mutate_request().
// Network-level 204 blocking of ad domains is intentionally disabled for SABR compatibility.
#[allow(dead_code)]
const AD_DOMAINS: &[&str] = &[
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "adservice.google.com",
];

const AD_CONFIG_KEYS: &[&str] = &[
    "adPlacements", // kept for contains_any_mutation_key fast-check; actual handling preserves them
    "adSlots",      // kept for contains_any_mutation_key fast-check; actual handling preserves them
    "playerAds",
    "adSlotRenderer",
    "inFeedAdLayoutRenderer",
    "promotedVideoRenderer",
    "promotedSparklesWebRenderer",
    "compactPromotedVideoRenderer",
    "statementBannerRenderer",
    "primetimeMastheadRenderer",
    "adsEngagementPanelContentRenderer",
];

const AFK_CONFIG_KEYS: &[&str] = &[
    "youThereRenderer",
    "lactThresholdMs",
    "you_there",
    "youThereData",
    "bkaEnforcementMessageViewModel",
    "enforcementMessageViewModel",
];

const YOUTUBE_STREAMING_NOISE_DOMAINS: &[&str] = &[
    "googlevideo.com",
    "c.youtube.com",
    "ytimg.com",
    "ggpht.com",
    "googleusercontent.com",
    "signaler-pa.youtube.com",
    "suggestqueries-clients6.youtube.com",
    "jnn-pa.googleapis.com",
];

const YOUTUBE_STREAMING_NOISE_PATHS: &[&str] = &[
    "/api/stats/",
    "/youtubei/v1/live_chat/",
    "/live_chat",
    "/youtubei/v1/updated_metadata",
    "/youtubei/v1/player/heartbeat",
    "/youtubei/v1/log_event",
    "/youtubei/v1/att/",
    "/youtubei/v1/feedback",
    "/youtubei/v1/notification/",
    "/api/jnn/",
    "/api/timedtext",
    "/api/manifest/",
    "/videoplayback",
    "/punctual/",
    "/generate_204",
    "/gen_204",
    "/error_204",
    "/csi_204",
    "/ptracking",
    "/pcs/activeview",
    "/pagead/",
    "/s/player/",
    "/s/desktop/",
    "/s/_/ytmainappweb/",
    "/s/_/ytembeds/",
    "/s/search/audio/",
    "/sw.js",
    "/iframe_api",
    "/getdatasyncidsendpoint",
];

const YOUTUBE_WATCHDOG_JS: &str = concat!(
    "(function(){if(window.__proxify_anti_afk__)return;window.__proxify_anti_afk__=true;",
    // Neutralize legacy Chrome Extension content script (youtube_anti_afk.js v1.5) if still loaded in browser
    "window.__proxify_ext_anti_afk_v15__=true;",
    "var TAG=\"[Proxify YouTube Shield]\";",
    // 1. Google ad_status spoof (anti-adblock detection bypass)
    "try{window.google_ad_status=1;}catch(e){}",
    // 2. ServiceWorker unregistration (prevent stale cache)
    "try{if(\"serviceWorker\" in navigator){navigator.serviceWorker.getRegistrations().then(function(regs){for(var i=0;i<regs.length;i++){regs[i].unregister();}});}}catch(e){}",
    // 3. Anti-AFK Visibility & LACT Freshness Shield
    "try{Object.defineProperty(document,\"hidden\",{get:function(){return false;},configurable:true});",
    "Object.defineProperty(document,\"visibilityState\",{get:function(){return \"visible\";},configurable:true});",
    "Object.defineProperty(document,\"webkitHidden\",{get:function(){return false;},configurable:true});",
    "Object.defineProperty(document,\"webkitVisibilityState\",{get:function(){return \"visible\";},configurable:true});",
    "document.addEventListener(\"visibilitychange\",function(e){e.stopImmediatePropagation();},true);",
    "}catch(e){}",
    "var userPaused=false;",
    "var mutedByAdSkipper=false;",
    "var rateModifiedByAdSkipper=false;",
    "function keepLactFresh(){try{var now=Date.now();window._lact=now;",
    "if(window.yt&&window.yt.config_){window.yt.config_._lact=now;}",
    "}catch(e){}}",
    "setInterval(keepLactFresh,5000);keepLactFresh();",
    // 4. AFK dialog dismiss helpers
    "function clickBtn(root){if(!root)return false;",
    "var sels=[\"#confirm-button button\",\"#confirm-button .yt-spec-button-shape-next\",\"yt-button-shape button\",\"#confirm-button a\",\"#confirm-button\",\".yt-confirm-dialog-renderer #confirm-button\",\"yt-you-there-renderer button\",\"ytmusic-you-there-renderer button\"];",
    "for(var i=0;i<sels.length;i++){var b=root.querySelector(sels[i]);if(b){",
    "if(b.shadowRoot){var inner=b.shadowRoot.querySelector(\"button\");if(inner){inner.click();return true;}}",
    "var nb=b.querySelector(\"button\")||b;nb.click();return true;}}",
    "var btns=root.querySelectorAll(\"button, a, tp-yt-paper-button, yt-button-renderer, yt-button-shape\");",
    "for(var j=0;j<btns.length;j++){var el=btns[j];var t=(el.textContent||\"\").trim().toLowerCase();var a=(el.getAttribute(\"aria-label\")||\"\").trim().toLowerCase();",
    "if(t===\"c\u{00f3}\"||t===\"yes\"||t===\"ok\"||t.indexOf(\"ti\u{1ebf}p t\u{1ee5}c\")!==-1||t.indexOf(\"continue\")!==-1||a===\"c\u{00f3}\"||a===\"yes\"||a.indexOf(\"ti\u{1ebf}p t\u{1ee5}c\")!==-1||a.indexOf(\"continue\")!==-1){",
    "var btnEl=el.querySelector(\"button\")||el;btnEl.click();return true;}}return false;}",
    "function resumeVideo(){try{if(userPaused)return;",
    "var v=document.querySelector(\"video.html5-main-video\")||document.querySelector(\"video\");",
    "if(v&&v.paused&&!v.ended&&v.readyState>=2){var p=v.play();if(p&&p.catch){p.catch(function(){",
    "var mp=document.getElementById(\"movie_player\");if(mp&&typeof mp.playVideo===\"function\"){mp.playVideo();}});};}",
    "var mp=document.getElementById(\"movie_player\");if(mp&&typeof mp.getPlayerState===\"function\"&&mp.getPlayerState()===2){if(typeof mp.playVideo===\"function\"){mp.playVideo();}}",
    "}catch(e){}}",
    "function dismissDialog(d){try{",
    "clickBtn(d);",
    "if(typeof d.close===\"function\"){d.close();}if(typeof d.cancel===\"function\"){d.cancel();}",
    "d.removeAttribute(\"opened\");d.style.display=\"none\";",
    "var backdrop=document.querySelector(\"tp-yt-iron-overlay-backdrop\");",
    "if(backdrop){backdrop.removeAttribute(\"opened\");backdrop.classList.remove(\"opened\");backdrop.style.display=\"none\";}",
    "}catch(e){}}",
    // 5. Ad fast-forward (Live & VOD Playlist safe) + CSS Ad-Overlay Shield + AFK dialog check interval
    // IMPORTANT:
    // - Never call synthetic .click() on .ytp-ad-skip-button or .ytp-skip-ad-button because base.js checks event.isTrusted!
    // - Never call player.skipAd() directly as it triggers SABR abnormality detection on playlists!
    // - Verify via player.getVideoStats().docid !== URLSearchParams(location.search).get("v") OR .ytp-ad-player-overlay
    //   that <video> is actually playing an instream ad clip before seeking video.currentTime = video.duration!
    //   In YouTube Playlists, <video.html5-main-video> is reused for the main song (duration 180-300s). If .ad-showing
    //   lingers for 150ms during transition or a side-by-side Live ad is active (docid === mainVid), seeking
    //   video.currentTime = video.duration would seek the MAIN SONG to the end and auto-skip the playlist!
    "try{var st=document.createElement(\"style\");st.id=\"proxify-yt-ad-style\";",
    "st.textContent=\".ytp-ad-overlay-container,.ytp-ad-text-overlay,.ytp-ad-image-overlay,#player-ads,ytd-companion-slot-renderer,ytd-action-companion-ad-renderer,ytd-in-feed-ad-layout-renderer,ytd-banner-promo-renderer,ytd-statement-banner-renderer,ytd-ad-slot-renderer,ytd-promoted-sparkles-web-renderer,ytd-Display-ad-renderer{display:none!important;}\";",
    "(document.head||document.documentElement).appendChild(st);}catch(e){}",
    "function checkAdsAndAfk(){try{",
    "if(!document.getElementById(\"proxify-yt-ad-style\")&&document.head){var st=document.createElement(\"style\");st.id=\"proxify-yt-ad-style\";st.textContent=\".ytp-ad-overlay-container,.ytp-ad-text-overlay,.ytp-ad-image-overlay,#player-ads,ytd-companion-slot-renderer,ytd-action-companion-ad-renderer,ytd-in-feed-ad-layout-renderer,ytd-banner-promo-renderer,ytd-statement-banner-renderer,ytd-ad-slot-renderer,ytd-promoted-sparkles-web-renderer{display:none!important;}\";document.head.appendChild(st);}",
    "var closeOverlay=document.querySelector(\".ytp-ad-overlay-close-button\");if(closeOverlay){closeOverlay.click();}",
    "var player=document.getElementById(\"movie_player\");var video=document.querySelector(\"video.html5-main-video\");",
    "var isAd=player&&(player.classList.contains(\"ad-showing\")||player.classList.contains(\"ad-interrupting\"));",
    "if(isAd&&video){",
    "var mainVid=\"\";try{mainVid=(new URLSearchParams(window.location.search)).get(\"v\")||\"\";}catch(e){}",
    "var stats=(typeof player.getVideoStats===\"function\")?player.getVideoStats():null;",
    "var curDocId=(stats&&stats.docid)?stats.docid:\"\";",
    "var isMainVideoLoaded=(mainVid&&curDocId&&curDocId===mainVid);",
    "if(!isMainVideoLoaded){",
    "if(!video.muted){video.muted=true;mutedByAdSkipper=true;}",
    "if(isFinite(video.duration)&&video.duration>0&&video.duration<=180){",
    "if(video.currentTime<video.duration-0.1){video.currentTime=video.duration;}",
    "}else if(video.playbackRate<16.0){video.playbackRate=16.0;rateModifiedByAdSkipper=true;}",
    "}else{",
    "if(mutedByAdSkipper){video.muted=false;mutedByAdSkipper=false;}",
    "if(rateModifiedByAdSkipper){video.playbackRate=1.0;rateModifiedByAdSkipper=false;}",
    "}",
    "}else if(video){",
    "if(mutedByAdSkipper){video.muted=false;mutedByAdSkipper=false;}",
    "if(rateModifiedByAdSkipper){video.playbackRate=1.0;rateModifiedByAdSkipper=false;}",
    "}",
    "}catch(e){}",
    "var dlgs=document.querySelectorAll(\"yt-confirm-dialog-renderer, tp-yt-paper-dialog, yt-you-there-renderer, ytmusic-you-there-renderer, ytd-modal-with-title-and-button-renderer, ytd-enforcement-message-view-model, ytd-popup-container tp-yt-paper-dialog\");",
    "for(var i=0;i<dlgs.length;i++){var d=dlgs[i];",
    "if(d.closest&&d.closest(\"ytd-live-chat-frame, #chat, #chat-messages\"))continue;",
    "var s=window.getComputedStyle(d);",
    "var hidden=d.hidden||d.getAttribute(\"aria-hidden\")==\"true\"||s.display===\"none\"||s.visibility===\"hidden\";",
    "var t=(d.textContent||\"\").toLowerCase();var tag=d.tagName.toLowerCase();",
    "var isAfk=t.indexOf(\"t\u{1ea1}m d\u{1eeb}ng\")!==-1||t.indexOf(\"ti\u{1ebf}p t\u{1ee5}c xem\")!==-1||t.indexOf(\"video paused\")!==-1||t.indexOf(\"continue watching\")!==-1||t.indexOf(\"still watching\")!==-1||t.indexOf(\"tr\u{00ec}nh ch\u{1eb7}n qu\u{1ea3}ng c\u{00e1}o\")!==-1||t.indexOf(\"ad blocker\")!==-1||tag===\"ytmusic-you-there-renderer\"||tag===\"yt-you-there-renderer\"||tag===\"ytd-enforcement-message-view-model\";",
    "if(!hidden&&isAfk){userPaused=false;dismissDialog(d);setTimeout(resumeVideo,50);setTimeout(resumeVideo,300);return true;}}",
    "var pd=document.querySelector(\"tp-yt-paper-dialog[opened]\");",
    "if(pd&&!(pd.closest&&pd.closest(\"ytd-live-chat-frame, #chat, #chat-messages\"))){var pt=(pd.textContent||\"\").toLowerCase();",
    "if(pt.indexOf(\"t\u{1ea1}m d\u{1eeb}ng\")!==-1||pt.indexOf(\"video paused\")!==-1||pt.indexOf(\"ti\u{1ebf}p t\u{1ee5}c xem\")!==-1||pt.indexOf(\"continue watching\")!==-1||pt.indexOf(\"tr\u{00ec}nh ch\u{1eb7}n qu\u{1ea3}ng c\u{00e1}o\")!==-1||pt.indexOf(\"ad blocker\")!==-1){",
    "userPaused=false;dismissDialog(pd);setTimeout(resumeVideo,50);setTimeout(resumeVideo,300);return true;}}return false;}",
    "setInterval(checkAdsAndAfk,150);document.addEventListener(\"yt-popup-opened\",checkAdsAndAfk);",
    "console.log(TAG,\"Anti-AFK Shield active (minimal mode)\");})();"
);

pub fn is_youtube_ad_request(_host: &str, _path: &str, _full_url: &str) -> bool {
    // CRITICAL SABR COMPATIBILITY (v8.4):
    // Do NOT return synthetic 204 No Content for ad network requests (doubleclick.net,
    // googlesyndication.com, /pagead/lvz, /youtubei/v1/player/ad_break, etc.)!
    // When ytInitialPlayerResponse or /youtubei/v1/player contains adPlacements/adSlots,
    // YouTube's SABR player fetches the ad payload and pings /pagead/lvz. If those requests
    // return an empty 204 response, SABR immediately triggers onAbnormalityDetected
    // (error 282054944) and auto-skips to the next video in the playlist!
    // Instead, ads are handled 100% safely on the client side by YOUTUBE_WATCHDOG_JS
    // (instant mute + fast-forward when curDocId !== mainVid, plus CSS overlay hiding).
    false
}

pub fn is_youtube_streaming_or_noise_request(host: &str, path: &str, content_type: &str) -> bool {
    let clean_domain = host.split(':').next().unwrap_or("").trim().to_lowercase();
    let clean_path = path.trim().to_lowercase();

    if clean_domain.is_empty() {
        return false;
    }

    if YOUTUBE_STREAMING_NOISE_DOMAINS
        .iter()
        .any(|d| clean_domain == *d || clean_domain.ends_with(&format!(".{}", d)))
    {
        return true;
    }

    let is_yt = clean_domain == "youtube.com"
        || clean_domain.ends_with(".youtube.com")
        || clean_domain == "youtu.be"
        || clean_domain.contains("youtubei");

    if !is_yt {
        if (clean_domain == "google.com" || clean_domain.ends_with(".google.com"))
            && (clean_path.starts_with("/punctual/") || clean_path.starts_with("/videoplayback"))
        {
            return true;
        }
        return false;
    }

    if YOUTUBE_STREAMING_NOISE_PATHS
        .iter()
        .any(|prefix| clean_path.starts_with(*prefix))
    {
        return true;
    }

    let ct = content_type.to_lowercase();
    if ct.starts_with("video/")
        || ct.starts_with("audio/")
        || ct.starts_with("image/")
        || ct.starts_with("font/")
        || ct.contains("application/vnd.yt-ump")
        || ct.contains("application/x-protobuf")
    {
        return true;
    }
    false
}

fn neutralize_you_there(ytr: &mut serde_json::Map<String, Value>) {
    ytr.insert("lactThresholdMs".to_string(), json!("86400000000"));
    ytr.insert("playbackPauseDelayMs".to_string(), json!("86400000000"));
    ytr.insert("promptDelaySec".to_string(), json!(86400000));
    ytr.insert("showPausedActions".to_string(), json!(false));
    if let Some(Value::Object(cfg)) = ytr.get_mut("configData") {
        if let Some(Value::Object(yt_data)) = cfg.get_mut("youThereData") {
            yt_data.insert("lactThresholdMs".to_string(), json!("86400000000"));
            yt_data.insert("playbackPauseDelayMs".to_string(), json!(86400000000_i64));
            yt_data.insert("promptDelaySec".to_string(), json!(86400000));
            yt_data.insert("showPausedActions".to_string(), json!(false));
        }
    }
}

/// Recursively neutralize ONLY AFK-related data (youThereRenderer, lactThresholdMs)
/// without touching ANY ad-related keys. Used for /player and /get_watch responses
/// where SABR integrity must be preserved.
fn neutralize_afk_only(val: &mut Value) -> bool {
    let mut modified = false;
    match val {
        Value::Object(map) => {
            if let Some(Value::Object(ytr)) = map.get_mut("youThereRenderer") {
                neutralize_you_there(ytr);
                modified = true;
            }
            if let Some(Value::Object(ytd)) = map.get_mut("youThereData") {
                neutralize_you_there(ytd);
                modified = true;
            }
            for (_, v) in map.iter_mut() {
                if neutralize_afk_only(v) {
                    modified = true;
                }
            }
        }
        Value::Array(arr) => {
            for item in arr.iter_mut() {
                if neutralize_afk_only(item) {
                    modified = true;
                }
            }
        }
        _ => {}
    }
    modified
}

pub fn clean_youtube_json_data(val: &mut Value) -> bool {
    let mut modified = false;
    match val {
        Value::Object(map) => {
            if let Some(Value::Object(ytr)) = map.get_mut("youThereRenderer") {
                neutralize_you_there(ytr);
                modified = true;
            }
            if let Some(Value::Object(ytd)) = map.get_mut("youThereData") {
                neutralize_you_there(ytd);
                modified = true;
            }

            // CRITICAL SABR COMPATIBILITY: Preserve adPlacements and adSlots INTACT!
            //
            // YouTube's SABR player calls REa(playerResponse) synchronously when a type-5
            // ad-wait context update arrives. REa() checks:
            //   adPlacements[].adPlacementRenderer.config.adPlacementConfig.kind === "AD_PLACEMENT_KIND_START"
            //   adSlots[].adSlotRenderer.adSlotMetadata.triggerEvent === "SLOT_TRIGGER_EVENT_BEFORE_CONTENT"
            //
            // If REa() returns false â†’ fires onAbnormalityDetected â†’ error 282054944 â†’ playlist auto-skip.
            // If we strip adPlacements/adSlots or replace with stubs missing renderer data,
            // the player either fails the check (no data) or fails to render the ad (no renderer).
            //
            // STRATEGY: Keep originals verbatim. Remove them before the recursive walk
            // (so the Array retain filter doesn't strip their internal adSlotRenderer items),
            // then re-insert them unchanged afterwards. The watchdog JS handles ad playback
            // by fast-forwarding via video.currentTime = video.duration.
            let saved_ad_placements = map.remove("adPlacements");
            let saved_ad_slots = map.remove("adSlots");

            for root_key in [
                "playerAds",
                "bkaEnforcementMessageViewModel",
                "enforcementMessageViewModel",
            ] {
                if map.remove(root_key).is_some() {
                    modified = true;
                }
            }

            if let Some(Value::Object(aux)) = map.get_mut("auxiliaryUi") {
                if let Some(Value::Object(mr)) = aux.get_mut("messageRenderers") {
                    for enf_key in [
                        "bkaEnforcementMessageViewModel",
                        "enforcementMessageViewModel",
                        "youThereRenderer",
                    ] {
                        if mr.remove(enf_key).is_some() {
                            modified = true;
                        }
                    }
                }
            }

            if let Some(Value::Array(messages)) = map.get_mut("messages") {
                let before = messages.len();
                messages.retain(|m| {
                    if let Value::Object(m_obj) = m {
                        if m_obj.contains_key("bkaEnforcementMessageViewModel")
                            || m_obj.contains_key("enforcementMessageViewModel")
                        {
                            return false;
                        }
                    }
                    true
                });
                if messages.len() != before {
                    modified = true;
                }
                for m in messages.iter_mut() {
                    if let Value::Object(m_obj) = m {
                        if let Some(Value::Object(ytr)) = m_obj.get_mut("youThereRenderer") {
                            neutralize_you_there(ytr);
                            modified = true;
                        }
                    }
                }
            }

            if let Some(Value::Object(wnr)) = map.get_mut("watchNextResponse") {
                if let Some(Value::Array(panels)) = wnr.get_mut("engagementPanels") {
                    let before = panels.len();
                    panels.retain(|p| {
                        p.get("engagementPanelSectionListRenderer")
                            .and_then(|r| r.get("targetId"))
                            .and_then(|t| t.as_str())
                            != Some("engagement-panel-ads")
                    });
                    if panels.len() != before {
                        modified = true;
                    }
                }
            }

            for (_, v) in map.iter_mut() {
                if clean_youtube_json_data(v) {
                    modified = true;
                }
            }

            // Re-insert the ORIGINAL adPlacements/adSlots unchanged.
            // They were temporarily removed to protect them from the recursive walk's
            // Array retain filter (which strips items containing "adSlotRenderer").
            if let Some(placements) = saved_ad_placements {
                map.insert("adPlacements".to_string(), placements);
            }
            if let Some(slots) = saved_ad_slots {
                map.insert("adSlots".to_string(), slots);
            }
        }
        Value::Array(arr) => {
            let before = arr.len();
            arr.retain(|item| {
                if item
                    .pointer("/command/reelWatchEndpoint/adClientParams/isAd")
                    .and_then(|v| v.as_bool())
                    == Some(true)
                {
                    return false;
                }
                if let Value::Object(obj) = item {
                    if let Some(content) = obj
                        .get("richItemRenderer")
                        .and_then(|r| r.get("content"))
                        .and_then(|c| c.as_object())
                    {
                        if content.contains_key("adSlotRenderer")
                            || content.contains_key("inFeedAdLayoutRenderer")
                        {
                            return false;
                        }
                    }
                    for ad_key in [
                        "adSlotRenderer",
                        "inFeedAdLayoutRenderer",
                        "promotedVideoRenderer",
                        "promotedSparklesWebRenderer",
                        "compactPromotedVideoRenderer",
                        "statementBannerRenderer",
                        "primetimeMastheadRenderer",
                    ] {
                        if obj.contains_key(ad_key) {
                            return false;
                        }
                    }
                }
                true
            });
            if arr.len() != before {
                modified = true;
            }
            for item in arr.iter_mut() {
                if clean_youtube_json_data(item) {
                    modified = true;
                }
            }
        }
        _ => {}
    }
    modified
}

fn contains_any_mutation_key(body: &str) -> bool {
    AD_CONFIG_KEYS
        .iter()
        .chain(AFK_CONFIG_KEYS.iter())
        .any(|k| body.contains(*k))
}

pub fn strip_youtube_ads(raw_text: &str) -> Option<String> {
    let trimmed = raw_text.trim();
    if trimmed.is_empty() || !contains_any_mutation_key(raw_text) {
        return None;
    }

    // 1. Fast path for Innertube JSON API responses
    if (trimmed.starts_with('{') && trimmed.ends_with('}'))
        || (trimmed.starts_with('[') && trimmed.ends_with(']'))
    {
        if let Ok(mut parsed) = serde_json::from_str::<Value>(trimmed) {
            if clean_youtube_json_data(&mut parsed) {
                return serde_json::to_string(&parsed).ok();
            }
            return None;
        }
    }

    // 2. HTML Watch / Shorts / Home pages
    let mut modified = false;
    let mut new_body = raw_text.to_string();

    static RE_INIT_PLAYER: OnceLock<Regex> = OnceLock::new();
    let re_player = RE_INIT_PLAYER.get_or_init(|| {
        Regex::new(r"(?s)(var\s+ytInitialPlayerResponse\s*=\s*)(\{.*?\})(\s*;\s*(?:var\s|window\.|</script>))")
            .unwrap()
    });

    // CRITICAL SABR COMPATIBILITY: Do NOT call clean_youtube_json_data on ytInitialPlayerResponse!
    // YouTube's SABR player reads this object to verify ad config consistency (REa() check).
    // Stripping playerAds while adPlacements/adSlots remain â†’ onAbnormalityDetected â†’ error 282054944.
    // We only neutralize AFK (youThereRenderer/youThereData) â€” the watchdog JS handles ads client-side.
    if let Some(caps) = re_player.captures(&new_body) {
        if let Some(j) = caps.get(2) {
            let json_slice = j.as_str();
            if json_slice.contains("youThere") || json_slice.contains("lactThresholdMs") {
                if let Ok(mut pr_data) = serde_json::from_str::<Value>(json_slice) {
                    if neutralize_afk_only(&mut pr_data) {
                        if let Ok(cleaned_json) = serde_json::to_string(&pr_data) {
                            let range = j.start()..j.end();
                            new_body.replace_range(range, &cleaned_json);
                            modified = true;
                        }
                    }
                }
            }
        }
    }

    // 2b. Also parse ytInitialData (feed/browse/search page data) for in-feed ad removal
    static RE_INIT_DATA: OnceLock<Regex> = OnceLock::new();
    let re_data = RE_INIT_DATA.get_or_init(|| {
        Regex::new(
            r"(?s)(var\s+ytInitialData\s*=\s*)(\{.*?\})(\s*;\s*(?:var\s|window\.|</script>))",
        )
        .unwrap()
    });

    if let Some(caps) = re_data.captures(&new_body) {
        if let Some(j) = caps.get(2) {
            let json_slice = j.as_str();
            if contains_any_mutation_key(json_slice) {
                if let Ok(mut init_data) = serde_json::from_str::<Value>(json_slice) {
                    if clean_youtube_json_data(&mut init_data) {
                        if let Ok(cleaned_json) = serde_json::to_string(&init_data) {
                            let range = j.start()..j.end();
                            new_body.replace_range(range, &cleaned_json);
                            modified = true;
                        }
                    }
                }
            }
        }
    }

    // REMOVED: Do NOT rename "playerAds" â†’ "playerAds_BLOCKED" in HTML text!
    // The ytInitialPlayerResponse is embedded as a JSON blob in the HTML.
    // A global text replace of "playerAds" hits that blob too, breaking the cross-key consistency
    // that SABR REa() checks (adPlacements + adSlots expect playerAds to exist).
    // The watchdog JS handles ad playback via fast-forward instead.

    // Neutralize any raw lactThresholdMs occurrences in HTML to 1000 days
    if new_body.contains("lactThresholdMs") {
        static RE_LACT: OnceLock<Regex> = OnceLock::new();
        let re_lact =
            RE_LACT.get_or_init(|| Regex::new(r#"("lactThresholdMs"\s*:\s*"?)\d+("?)"#).unwrap());
        let replaced = re_lact.replace_all(&new_body, "${1}86400000000${2}");
        if replaced != new_body {
            new_body = replaced.into_owned();
            modified = true;
        }
    }

    if modified {
        Some(new_body)
    } else {
        None
    }
}

pub fn inject_youtube_anti_afk_with_nonce(html: &str, csp_nonce: &str) -> String {
    if html.is_empty() || html.contains("__proxify_anti_afk__") {
        return html.to_string();
    }

    let mut out = strip_youtube_ads(html).unwrap_or_else(|| html.to_string());

    let mut nonce = csp_nonce.to_string();
    if nonce.is_empty() {
        static RE_SCRIPT_NONCE: OnceLock<Regex> = OnceLock::new();
        let re_nonce = RE_SCRIPT_NONCE
            .get_or_init(|| Regex::new(r#"<script\s+[^>]*nonce="([^"]+)""#).unwrap());
        if let Some(caps) = re_nonce.captures(&out) {
            if let Some(m) = caps.get(1) {
                nonce = m.as_str().to_string();
            }
        }
    }

    let nonce_attr = if nonce.is_empty() {
        String::new()
    } else {
        format!(" nonce=\"{}\"", nonce)
    };
    let script_tag = format!(
        "<script id=\"proxify-yt-watchdog\"{}>{}</script>",
        nonce_attr, YOUTUBE_WATCHDOG_JS
    );

    // Inject immediately after opening <head...> so our JS runtime hooks (HTMLDivElement.prototype.addEventListener,
    // Promise.prototype.then, JSON.stringify, Array.prototype.push, Map.prototype.has, google_ad_status)
    // execute BEFORE YouTube's inline scripts, base.js, and ytmainappweb!
    static RE_HEAD_OPEN: OnceLock<Regex> = OnceLock::new();
    let re_head = RE_HEAD_OPEN.get_or_init(|| Regex::new(r"(?i)<head(?:\s[^>]*)?>").unwrap());

    if let Some(m) = re_head.find(&out) {
        out.insert_str(m.end(), &script_tag);
    } else if let Some(pos) = out.rfind("</head>") {
        out.insert_str(pos, &script_tag);
    } else if let Some(pos) = out.rfind("</body>") {
        out.insert_str(pos, &script_tag);
    } else {
        out.push_str(&script_tag);
    }
    out
}

pub fn inject_youtube_anti_afk(html: &str) -> String {
    inject_youtube_anti_afk_with_nonce(html, "")
}

fn insert_spec_valid_cors_headers(
    req_method: &str,
    req_headers: &HashMap<String, String>,
    resp_headers: &mut HashMap<String, String>,
) {
    let origin = req_headers
        .iter()
        .find(|(k, _)| k.eq_ignore_ascii_case("origin"))
        .map(|(_, v)| v.trim().to_string())
        .filter(|v| !v.is_empty());

    // Fetch/CORS specification forbids sending `Access-Control-Allow-Origin: *` together with
    // `Access-Control-Allow-Credentials: true` (causes a hard CORS TypeError in Chromium).
    if let Some(orig) = origin {
        resp_headers.insert("access-control-allow-origin".to_string(), orig);
        resp_headers.insert(
            "access-control-allow-credentials".to_string(),
            "true".to_string(),
        );
        resp_headers.insert("vary".to_string(), "Origin".to_string());
    } else {
        resp_headers.insert("access-control-allow-origin".to_string(), "*".to_string());
    }

    resp_headers.insert(
        "cross-origin-resource-policy".to_string(),
        "cross-origin".to_string(),
    );
    resp_headers.insert("timing-allow-origin".to_string(), "*".to_string());

    if req_method.eq_ignore_ascii_case("options") {
        resp_headers.insert(
            "access-control-allow-methods".to_string(),
            "GET, POST, OPTIONS, HEAD".to_string(),
        );
        resp_headers.insert(
            "access-control-allow-headers".to_string(),
            "Content-Type, Authorization, X-Goog-AuthUser, X-Youtube-Client-Name, X-Youtube-Client-Version"
                .to_string(),
        );
    }
}

pub struct YouTubePlugin;

#[async_trait]
impl MutatorInterceptor for YouTubePlugin {
    async fn mutate_request(&self, flow: &mut HttpFlow) {
        let host = flow.request.host.to_lowercase();
        let clean_host = host.split(':').next().unwrap_or("").trim();
        let path_only = flow
            .request
            .path
            .split('?')
            .next()
            .unwrap_or("")
            .to_lowercase();
        if (clean_host == "youtube.com" || clean_host.ends_with(".youtube.com"))
            && (path_only == "/sw.js" || path_only == "/service_worker.js")
        {
            info!(
                "ðŸ›¡ï¸ [YouTube Anti-AFK] Neutralized ServiceWorker cache: {}",
                flow.request.url
            );
            let mut headers = HashMap::new();
            headers.insert(
                "content-type".to_string(),
                "application/javascript; charset=utf-8".to_string(),
            );
            headers.insert(
                "cache-control".to_string(),
                "no-store, no-cache, must-revalidate, max-age=0".to_string(),
            );
            // NOTE: Never emit `Clear-Site-Data: "storage"` here â€” wiping IndexedDB/LocalStorage
            // mid-playback destroys YouTube's cached BotGuard PO tokens and player state.
            let sw_kill_js = "self.addEventListener('install',function(){self.skipWaiting();});self.addEventListener('activate',function(e){e.waitUntil(self.registration.unregister());});";
            flow.response = Some(FlowResponse {
                status_code: 200,
                headers,
                content: sw_kill_js.as_bytes().to_vec().into(),
            });
            return;
        }

        // Force cache-busting on YouTube Watch/Home HTML so browser never reuses un-injected cached HTML
        if (clean_host == "youtube.com" || clean_host.ends_with(".youtube.com"))
            && (path_only.starts_with("/watch")
                || path_only.starts_with("/shorts")
                || path_only.starts_with("/live")
                || path_only == "/")
        {
            flow.request.headers.retain(|k, _| {
                !matches!(
                    k.to_lowercase().as_str(),
                    "if-none-match" | "if-modified-since"
                )
            });
        }

        // Spoof YouTube's two DoubleClick anti-adblock bait endpoints so base.js reports DCLKSTAT=1
        // and clean XSSI JSON instead of detecting ad-blocking via network/CORS errors.
        let is_doubleclick =
            clean_host == "doubleclick.net" || clean_host.ends_with(".doubleclick.net");
        if is_doubleclick && path_only.ends_with("/ad_status.js") {
            let mut headers = HashMap::new();
            headers.insert(
                "content-type".to_string(),
                "text/javascript; charset=utf-8".to_string(),
            );
            headers.insert("cache-control".to_string(), "no-store".to_string());
            insert_spec_valid_cors_headers(
                &flow.request.method,
                &flow.request.headers,
                &mut headers,
            );
            flow.response = Some(FlowResponse {
                status_code: 200,
                headers,
                content: b"window.google_ad_status = 1;".to_vec().into(),
            });
            return;
        }

        if is_doubleclick && (path_only == "/pagead/id" || path_only.starts_with("/pagead/id/")) {
            let mut headers = HashMap::new();
            headers.insert(
                "content-type".to_string(),
                "application/json; charset=ISO-8859-1".to_string(),
            );
            headers.insert("cache-control".to_string(), "no-store".to_string());
            insert_spec_valid_cors_headers(
                &flow.request.method,
                &flow.request.headers,
                &mut headers,
            );
            flow.response = Some(FlowResponse {
                status_code: 200,
                headers,
                content: b")]}'\n\n{\"id\":\"\",\"type\":1}".to_vec().into(),
            });
            return;
        }

        if is_youtube_ad_request(&flow.request.host, &flow.request.path, &flow.request.url) {
            info!(
                "ðŸš« [YouTube AdBlock] Blocked: {} {}",
                flow.request.method,
                &flow.request.url[..flow.request.url.len().min(120)]
            );
            let mut headers = HashMap::new();
            headers.insert("content-type".to_string(), "text/plain".to_string());
            insert_spec_valid_cors_headers(
                &flow.request.method,
                &flow.request.headers,
                &mut headers,
            );
            flow.response = Some(FlowResponse {
                status_code: 204,
                headers,
                content: Vec::new().into(),
            });
        }
    }

    async fn mutate_response(&self, flow: &mut HttpFlow) {
        let host = flow.request.host.to_lowercase();
        let path = flow.request.path.to_lowercase();
        let ct = flow.response_content_type();

        let is_yt =
            host == "youtube.com" || host.ends_with(".youtube.com") || host.contains("youtubei");
        if !is_yt {
            return;
        }

        let resp = match flow.response.as_mut() {
            Some(r) if !r.content.is_empty() => r,
            _ => return,
        };

        if !ct.contains("text/html") && !ct.contains("json") {
            return;
        }

        // 1. Innertube API JSON responses (/youtubei/v1/player, get_watch, next, browse, search, etc.)
        if path.contains("youtubei/v1") && ct.contains("json") {
            // NEVER touch these endpoints
            if path.contains("/log_event")
                || path.contains("/feedback")
                || path.contains("/updated_metadata")
                || path.contains("/live_chat/")
                || path.contains("/notification/")
                || path.contains("/att/")
            {
                return;
            }

            // CRITICAL SABR COMPATIBILITY: Do NOT strip ads from /player or /get_watch responses!
            // YouTube SABR checks overall consistency of playerResponse â€” if adPlacements exist
            // but playerAds/enforcement messages are stripped, or if any ad config key is missing,
            // onAbnormalityDetected fires synchronously â†’ error 282054944 â†’ playlist auto-skip.
            // The watchdog JS handles ad playback by fast-forwarding on the client side.
            if path.contains("/player") || path.contains("/get_watch") {
                // Only neutralize AFK (youThereRenderer) in player responses, leave ads intact.
                // Fast pre-check avoids parsing 100KB-500KB JSON when no AFK keys exist.
                let content_bytes = std::mem::take(&mut resp.content);
                let modified_opt = std::str::from_utf8(&content_bytes).ok().and_then(|text| {
                    if !text.contains("youThere") && !text.contains("lactThresholdMs") {
                        return None;
                    }
                    let trimmed = text.trim();
                    if !trimmed.starts_with('{') || !trimmed.ends_with('}') {
                        return None;
                    }
                    if let Ok(mut parsed) = serde_json::from_str::<Value>(trimmed) {
                        if neutralize_afk_only(&mut parsed) {
                            return serde_json::to_string(&parsed).ok();
                        }
                    }
                    None
                });
                if let Some(modified_json) = modified_opt {
                    resp.content = modified_json.into_bytes().into();
                    debug!(
                        "ðŸ›¡ï¸ [YouTube Anti-AFK] Neutralized AFK in player API: {}",
                        &path[..path.len().min(60)]
                    );
                } else {
                    resp.content = content_bytes;
                }
                return;
            }
            // ALL other Innertube JSON API endpoints (/next, /browse, /search, /guide, etc.)
            // are also zero-touched for SABR compatibility. When playlist auto-advances via
            // SPA navigation, YouTube calls /next which may contain embedded player/ad data.
            // Stripping any ad keys from /next breaks SABR's cross-endpoint consistency checks,
            // causing error 282054944 and playlist auto-skip on subsequent videos.
            //
            // Only AFK neutralization is applied. In-feed ad removal is done in the HTML path
            // (ytInitialData in watch/home pages) where it doesn't affect SABR.
            let content_bytes = std::mem::take(&mut resp.content);
            let modified_opt = std::str::from_utf8(&content_bytes).ok().and_then(|text| {
                if !text.contains("youThere") && !text.contains("lactThresholdMs") {
                    return None;
                }
                let trimmed = text.trim();
                if !trimmed.starts_with('{') || !trimmed.ends_with('}') {
                    return None;
                }
                if let Ok(mut parsed) = serde_json::from_str::<Value>(trimmed) {
                    if neutralize_afk_only(&mut parsed) {
                        return serde_json::to_string(&parsed).ok();
                    }
                }
                None
            });

            if let Some(modified_json) = modified_opt {
                resp.content = modified_json.into_bytes().into();
                debug!(
                    "ðŸ›¡ï¸ [YouTube Anti-AFK] Neutralized AFK in API: {}",
                    &path[..path.len().min(60)]
                );
            } else {
                resp.content = content_bytes;
            }
            return;
        }

        // 2. HTML Watch / Shorts / Home / Live pages (NEVER inject into /live_chat or /rotatecookiespage iframes)
        let path_only = path.split('?').next().unwrap_or("");
        let is_watch_or_home = path_only.starts_with("/watch")
            || path_only.starts_with("/shorts")
            || path_only.starts_with("/live")
            || path_only.starts_with("/channel/")
            || path_only.starts_with("/c/")
            || path_only.starts_with("/@")
            || path_only == "/"
            || path_only.is_empty();
        let is_iframe_util = path_only.starts_with("/live_chat")
            || path_only.starts_with("/rotatecookiespage")
            || path_only.starts_with("/embed/");

        if ct.contains("text/html") && is_watch_or_home && !is_iframe_util {
            let mut csp_keys = Vec::new();
            let mut extracted_nonce = String::new();

            static RE_CSP_NONCE: OnceLock<Regex> = OnceLock::new();
            let re_nonce = RE_CSP_NONCE.get_or_init(|| Regex::new(r"'nonce-([^']+)'").unwrap());

            for (k, v) in &resp.headers {
                if k.eq_ignore_ascii_case("content-security-policy")
                    || k.eq_ignore_ascii_case("content-security-policy-report-only")
                {
                    if extracted_nonce.is_empty() {
                        if let Some(caps) = re_nonce.captures(v) {
                            if let Some(m) = caps.get(1) {
                                extracted_nonce = m.as_str().to_string();
                            }
                        }
                    }
                    csp_keys.push((k.clone(), v.clone()));
                }
            }

            static RE_CSP_TRUSTED: OnceLock<Regex> = OnceLock::new();
            let re_trusted = RE_CSP_TRUSTED.get_or_init(|| {
                Regex::new(r"(?i),?\s*require-trusted-types-for\s+'script'\s*;?").unwrap()
            });

            for (k, v) in csp_keys {
                let mut new_csp = re_trusted.replace_all(&v, "").to_string();
                new_csp = new_csp.replace("trusted-types ", "trusted-types * ");
                resp.headers.insert(k, new_csp);
            }

            let content_bytes = std::mem::take(&mut resp.content);
            let orig_len = content_bytes.len();
            let nonce_clone = extracted_nonce;
            let modified_opt = tokio::task::spawn_blocking(move || {
                std::str::from_utf8(&content_bytes)
                    .ok()
                    .map(|raw_html| inject_youtube_anti_afk_with_nonce(raw_html, &nonce_clone))
                    .ok_or(content_bytes)
            })
            .await;

            match modified_opt {
                Ok(Ok(modified_html)) => {
                    if modified_html.len() != orig_len {
                        info!(
                            "ðŸ›¡ï¸ [YouTube AdBlock] Injected Watchdog & stripped HTML ads: {}",
                            &path[..path.len().min(60)]
                        );
                    }
                    resp.content = modified_html.into_bytes().into();
                }
                Ok(Err(orig)) => {
                    resp.content = orig;
                }
                Err(_) => {}
            }
        }
    }
}

pub struct YouTubeRecordFilter;

impl RecordFilter for YouTubeRecordFilter {
    fn should_record(&self, flow: &HttpFlow) -> bool {
        if is_youtube_ad_request(&flow.request.host, &flow.request.path, &flow.request.url) {
            return false;
        }
        let ct = flow.response_content_type();
        if is_youtube_streaming_or_noise_request(&flow.request.host, &flow.request.path, &ct) {
            return false;
        }
        true
    }
}

pub struct YouTubeExtension;

impl YouTubeExtension {
    pub fn new() -> Self {
        Self
    }
}

impl Default for YouTubeExtension {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl BaseExtension for YouTubeExtension {
    fn name(&self) -> &str {
        "youtube"
    }

    async fn on_init(&self, context: &mut ExtensionContext) -> Result<(), String> {
        let plugin = Arc::new(YouTubePlugin);
        for domain in [
            "*.youtube.com",
            "youtube.com",
            "*.youtu.be",
            "youtu.be",
            "*.youtube-nocookie.com",
            "youtube-nocookie.com",
            "*.googleapis.com",
            "youtubei.googleapis.com",
            "*.doubleclick.net",
            "doubleclick.net",
            "*.googlesyndication.com",
            "googlesyndication.com",
            "*.googleadservices.com",
            "googleadservices.com",
            "*.google.com",
            "adservice.google.com",
        ] {
            context.register_mutator(domain, plugin.clone());
        }

        for stream_domain in [
            "*.googlevideo.com",
            "*.ytimg.com",
            "*.ggpht.com",
            "*.googleusercontent.com",
        ] {
            context.register_stream_rule(stream_domain);
        }

        const YOUTUBE_STREAM_PATHS: &[&str] = &[
            "/live_chat",
            "/youtubei/v1/live_chat/",
            "/youtubei/v1/log_event",
            "/youtubei/v1/feedback",
            "/youtubei/v1/updated_metadata",
            "/youtubei/v1/notification/",
            "/youtubei/v1/att/",
            "/api/stats/",
            "/videoplayback",
            "/api/manifest/",
            "/punctual/",
            "/rotatecookiespage",
            "/generate_204",
            "/gen_204",
            "/error_204",
            "/csi_204",
            "/s/player/",
            "/s/desktop/",
            "/s/_/ytmainappweb/",
        ];

        for domain in [
            "*.youtube.com",
            "youtube.com",
            "*.googlevideo.com",
            "googlevideo.com",
            "*.google.com",
            "google.com",
            "*.googleapis.com",
            "youtubei.googleapis.com",
        ] {
            for path in YOUTUBE_STREAM_PATHS {
                context.register_stream_path_rule(domain, path);
            }
        }

        context.register_record_filter(Arc::new(YouTubeRecordFilter));
        info!("[Extension: YouTube] Registered AdBlock, Anti-AFK (with CSP Nonce), Stream Rules & Path Rules.");
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_ad_detection_and_json_cleaning() {
        // Network-level 204 ad blocking is disabled so YouTube SABR does not trigger
        // onAbnormalityDetected (error 282054944) and auto-skip playlists.
        assert!(
            !is_youtube_ad_request(
                "www.youtube.com",
                "/youtubei/v1/player/ad_break",
                "https://www.youtube.com/youtubei/v1/player/ad_break"
            ),
            "ad_break must pass through to prevent SABR playlist auto-skip"
        );
        assert!(
            !is_youtube_ad_request(
                "www.google.com",
                "/pagead/lvz?evtid=123",
                "https://www.google.com/pagead/lvz?evtid=123"
            ),
            "/pagead/lvz must pass through to prevent SABR playlist auto-skip"
        );
        assert!(
            !is_youtube_ad_request(
                "www.youtube.com",
                "/watch",
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            ),
            "normal watch URL must not be blocked"
        );

        let mut data = json!({
            "videoDetails": { "videoId": "123" },
            "adPlacements": [{ "ad": 1 }],
            "playerAds": [{ "ad": 2 }],
            "auxiliaryUi": {
                "messageRenderers": {
                    "bkaEnforcementMessageViewModel": { "isVisible": true }
                }
            },
            "messages": [
                {
                    "youThereRenderer": {
                        "lactThresholdMs": "1000",
                        "configData": {
                            "youThereData": {
                                "lactThresholdMs": "1000",
                                "playbackPauseDelayMs": 10000
                            }
                        }
                    }
                }
            ]
        });
        assert!(clean_youtube_json_data(&mut data));
        // adPlacements preserved intact for SABR REa() check
        assert!(
            data.get("adPlacements").is_some(),
            "adPlacements must be preserved for SABR compatibility"
        );
        assert!(data.get("playerAds").is_none());
        assert!(data["auxiliaryUi"]["messageRenderers"]
            .get("bkaEnforcementMessageViewModel")
            .is_none());
        assert_eq!(
            data["messages"][0]["youThereRenderer"]["lactThresholdMs"],
            "86400000000"
        );
        assert_eq!(
            data["messages"][0]["youThereRenderer"]["configData"]["youThereData"]
                ["lactThresholdMs"],
            "86400000000"
        );
    }

    #[test]
    fn test_html_ad_pruning_and_head_first_nonce_injection() {
        let html = r#"<html><head><script nonce="abc123xyz">var ytInitialPlayerResponse = {"adPlacements":[{"id":1}],"videoDetails":{"id":"v1"}}; var ytInitialData = {"adSlots":[{"s":1}]};</script></head><body></body></html>"#;
        let out = inject_youtube_anti_afk_with_nonce(html, "");
        // adPlacements preserved for SABR compatibility (not stripped, not renamed)
        assert!(
            out.contains("\"adPlacements\""),
            "adPlacements must be preserved in HTML for SABR REa() check"
        );
        // adSlots preserved for SABR compatibility
        assert!(
            out.contains("\"adSlots\""),
            "adSlots must be preserved in HTML for SABR compatibility"
        );
        assert!(out.contains("nonce=\"abc123xyz\""));

        let watchdog_pos = out
            .find("id=\"proxify-yt-watchdog\"")
            .expect("watchdog script must be present");
        let inline_pos = out
            .find("var ytInitialPlayerResponse")
            .expect("inline player script must be present");
        assert!(
            watchdog_pos < inline_pos,
            "Watchdog script must execute in <head> BEFORE YouTube inline scripts"
        );
        assert!(
            !YOUTUBE_WATCHDOG_JS.contains(".ytp-ad-skip-button")
                && !YOUTUBE_WATCHDOG_JS.contains(".ytp-skip-ad-button")
                && !YOUTUBE_WATCHDOG_JS.contains("player.skipAd"),
            "Watchdog must never invoke untrusted synthetic .click() on skip buttons or player.skipAd()"
        );
        assert!(
            YOUTUBE_WATCHDOG_JS.contains("getVideoStats")
                && YOUTUBE_WATCHDOG_JS.contains("isMainVideoLoaded"),
            "Watchdog must verify docid !== mainVid before seeking video.currentTime to prevent playlist auto-skip"
        );
    }

    #[test]
    fn test_attestation_and_heartbeat_preserved_for_sabr() {
        assert!(
            !is_youtube_ad_request(
                "www.youtube.com",
                "/youtubei/v1/att/get?prettyPrint=false",
                "https://www.youtube.com/youtubei/v1/att/get?prettyPrint=false"
            ),
            "BotGuard PO Token attestation endpoint must NEVER be blocked"
        );

        let mut player_json = json!({
            "videoDetails": { "videoId": "FmbKnhhO1rg" },
            "adBreakHeartbeatParams": "Q0FBJTNE",
            "adPlacements": [{ "adPlacementRenderer": {} }],
            "playerAds": [{ "ad": 1 }]
        });
        assert!(clean_youtube_json_data(&mut player_json));
        // adPlacements preserved for SABR
        assert!(
            player_json.get("adPlacements").is_some(),
            "adPlacements must be preserved for SABR compatibility"
        );
        // playerAds removed
        assert!(player_json.get("playerAds").is_none());
        assert_eq!(
            player_json
                .get("adBreakHeartbeatParams")
                .and_then(|v| v.as_str()),
            Some("Q0FBJTNE"),
            "adBreakHeartbeatParams must be preserved so SABR heartbeat checks stay consistent"
        );
    }

    #[test]
    fn test_sabr_ad_placement_preserved_verbatim() {
        // adPlacements and adSlots must be preserved EXACTLY as received
        // so YouTube's SABR REa() check passes and ads can be fast-forwarded
        // by the watchdog JS instead of causing error 282054944.
        let mut data = json!({
            "videoDetails": { "videoId": "FmbKnhhO1rg" },
            "adPlacements": [{
                "adPlacementRenderer": {
                    "config": {
                        "adPlacementConfig": {
                            "kind": "AD_PLACEMENT_KIND_START"
                        }
                    },
                    "renderer": { "clientForecastingAdRenderer": {} }
                }
            }],
            "adSlots": [{
                "adSlotRenderer": {
                    "adSlotMetadata": {
                        "triggerEvent": "SLOT_TRIGGER_EVENT_BEFORE_CONTENT"
                    },
                    "fulfillmentContent": { "fulfilledLayout": {} }
                }
            }],
            "adBreakHeartbeatParams": "Q0FBJTNE",
            "playerAds": [{ "ad": 1 }]
        });

        let original_placements = data["adPlacements"].clone();
        let original_slots = data["adSlots"].clone();

        assert!(clean_youtube_json_data(&mut data));

        // adPlacements preserved verbatim (including renderer data)
        assert_eq!(
            data.get("adPlacements").unwrap(),
            &original_placements,
            "adPlacements must be preserved verbatim for SABR"
        );

        // adSlots preserved verbatim (including fulfillment content)
        assert_eq!(
            data.get("adSlots").unwrap(),
            &original_slots,
            "adSlots must be preserved verbatim for SABR"
        );

        // adBreakHeartbeatParams preserved
        assert_eq!(
            data.get("adBreakHeartbeatParams").and_then(|v| v.as_str()),
            Some("Q0FBJTNE"),
            "adBreakHeartbeatParams must be preserved"
        );

        // playerAds still removed
        let mut data2 = json!({
            "playerAds": [{ "ad": 1 }],
            "adPlacements": [{ "x": 1 }]
        });
        assert!(clean_youtube_json_data(&mut data2));
        assert!(data2.get("playerAds").is_none());
        assert!(data2.get("adPlacements").is_some());
    }

    #[test]
    fn test_sabr_ad_data_preserved_in_html() {
        // When ytInitialPlayerResponse has adPlacements, they must survive
        // intact in the final HTML output (not renamed, not stripped).
        let html = r#"<html><head><script nonce="x1">var ytInitialPlayerResponse = {"adPlacements":[{"adPlacementRenderer":{"config":{"adPlacementConfig":{"kind":"AD_PLACEMENT_KIND_START"}},"renderer":{"ad":"data"}}}],"videoDetails":{"id":"v1"}};</script></head><body></body></html>"#;
        let out = inject_youtube_anti_afk_with_nonce(html, "");
        // adPlacements preserved verbatim (not renamed to _BLOCKED, not stripped)
        assert!(
            out.contains("\"adPlacements\""),
            "adPlacements must be preserved in HTML for SABR REa()"
        );
        assert!(
            out.contains("AD_PLACEMENT_KIND_START"),
            "Placement kind marker must survive"
        );
        // Renderer data also preserved (needed for SABR ad rendering/fast-forward)
        assert!(
            out.contains("\"ad\":\"data\""),
            "Renderer data must be preserved for SABR"
        );
    }

    #[tokio::test]
    async fn test_doubleclick_bait_spoofing_cors_and_sw_storage_safety() {
        use proxify_sdk::FlowRequest;

        let plugin = YouTubePlugin;

        // 1. /sw.js must NOT emit Clear-Site-Data
        let mut sw_flow = HttpFlow {
            request: FlowRequest {
                method: "GET".to_string(),
                url: "https://www.youtube.com/sw.js".to_string(),
                host: "www.youtube.com".to_string(),
                port: 443,
                path: "/sw.js".to_string(),
                scheme: "https".to_string(),
                headers: HashMap::new(),
                content: Vec::new().into(),
                timestamp_start: 0.0,
            },
            response: None,
        };
        plugin.mutate_request(&mut sw_flow).await;
        let sw_resp = sw_flow.response.expect("sw.js must return synthetic 200");
        assert_eq!(sw_resp.status_code, 200);
        assert!(
            !sw_resp.headers.contains_key("clear-site-data"),
            "sw.js must not wipe IndexedDB/LocalStorage via Clear-Site-Data"
        );

        // 2. static.doubleclick.net/instream/ad_status.js -> 200 + window.google_ad_status = 1;
        let mut dclk_js = HttpFlow {
            request: FlowRequest {
                method: "GET".to_string(),
                url: "https://static.doubleclick.net/instream/ad_status.js".to_string(),
                host: "static.doubleclick.net".to_string(),
                port: 443,
                path: "/instream/ad_status.js".to_string(),
                scheme: "https".to_string(),
                headers: HashMap::new(),
                content: Vec::new().into(),
                timestamp_start: 0.0,
            },
            response: None,
        };
        plugin.mutate_request(&mut dclk_js).await;
        let dclk_resp = dclk_js
            .response
            .expect("ad_status.js must return spoofed 200");
        assert_eq!(dclk_resp.status_code, 200);
        assert_eq!(
            std::str::from_utf8(&dclk_resp.content).unwrap(),
            "window.google_ad_status = 1;"
        );

        // 3. googleads.g.doubleclick.net/pagead/id with Origin -> 200 + reflected ACAO + XSSI JSON
        let mut req_headers = HashMap::new();
        req_headers.insert("Origin".to_string(), "https://www.youtube.com".to_string());
        let mut pagead_id = HttpFlow {
            request: FlowRequest {
                method: "GET".to_string(),
                url: "https://googleads.g.doubleclick.net/pagead/id?slf_rd=1".to_string(),
                host: "googleads.g.doubleclick.net".to_string(),
                port: 443,
                path: "/pagead/id?slf_rd=1".to_string(),
                scheme: "https".to_string(),
                headers: req_headers.clone(),
                content: Vec::new().into(),
                timestamp_start: 0.0,
            },
            response: None,
        };
        plugin.mutate_request(&mut pagead_id).await;
        let id_resp = pagead_id
            .response
            .expect("/pagead/id must return spoofed 200");
        assert_eq!(id_resp.status_code, 200);
        assert_eq!(
            id_resp
                .headers
                .get("access-control-allow-origin")
                .map(String::as_str),
            Some("https://www.youtube.com")
        );
        assert_eq!(
            id_resp
                .headers
                .get("access-control-allow-credentials")
                .map(String::as_str),
            Some("true")
        );
        assert!(std::str::from_utf8(&id_resp.content)
            .unwrap()
            .starts_with(")]}'"));

        // 4. Generic ad requests are NOT blocked with 204 (SABR compatibility).
        let mut generic_ad = HttpFlow {
            request: FlowRequest {
                method: "POST".to_string(),
                url: "https://www.youtube.com/api/stats/ads".to_string(),
                host: "www.youtube.com".to_string(),
                port: 443,
                path: "/api/stats/ads".to_string(),
                scheme: "https".to_string(),
                headers: HashMap::new(),
                content: Vec::new().into(),
                timestamp_start: 0.0,
            },
            response: None,
        };
        plugin.mutate_request(&mut generic_ad).await;
        assert!(
            generic_ad.response.is_none(),
            "Generic ad requests must pass through for SABR compatibility"
        );
    }
}
