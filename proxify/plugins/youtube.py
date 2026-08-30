"""YouTube Plugin."""

from typing import Any
from mitmproxy import http
from proxify.plugins.registry import register_plugin
from proxify.plugins.base import BasePlugin
from proxify.utils.youtube_utils import is_youtube_ad_request, strip_youtube_ads

@register_plugin("youtube")
class YouTubePlugin(BasePlugin):
    name = "YouTube Enhancer"
    description = "Chặn quảng cáo và tracking trên YouTube"
    target_domains = ["youtube.com", "googlevideo.com", "youtubei", "doubleclick.net"]
    
    async def on_request(self, flow: Any) -> None:
        """Block ads and tracking requests."""
        if not isinstance(flow, http.HTTPFlow):
            return

        domain = flow.request.pretty_host
        # Fast skip: only process YouTube domains
        if 'youtube.com' not in domain and 'googlevideo.com' not in domain and 'youtubei' not in domain and 'doubleclick.net' not in domain:
            return

        url = flow.request.pretty_url
        
        if is_youtube_ad_request(url, domain):
            self.logger.info(f"🚫 [BLOCKED BY {self.name}] {flow.request.method} {url}")
            flow.metadata["ad_blocked"] = True
            flow.kill()

    async def on_response(self, flow: Any) -> None:
        """Strip ads from responses."""
        if not isinstance(flow, http.HTTPFlow):
            return

        domain = flow.request.pretty_host
        # Fast skip: only process YouTube domains
        if 'youtube.com' not in domain and 'googlevideo.com' not in domain:
            return

        url = flow.request.pretty_url
        is_api = 'youtubei/v1' in url
        is_watch_page = 'youtube.com/watch' in url
        
        if not is_api and not is_watch_page:
            return

        if not flow.response or not flow.response.content:
            return

        try:
            body = flow.response.content.decode("utf-8")
        except (UnicodeDecodeError, Exception):
            return
            
        if not body:
            return
            
        modified, new_body = strip_youtube_ads(body)

        # Inject auto-confirm script into HTML
        if is_watch_page and "text/html" in flow.response.headers.get("Content-Type", "").lower():
            script = """
            <script>
            (function() {
                'use strict';
                setInterval(() => {
                    // Find the dialog
                    const dialogs = document.querySelectorAll('yt-confirm-dialog-renderer, tp-yt-paper-dialog, ytd-popup-container');
                    let dialogFound = false;
                    
                    dialogs.forEach(dialog => {
                        // Check if it's the "Video paused" dialog
                        if (dialog.style.display !== 'none' && (dialog.innerText.includes('tạm dừng') || dialog.innerText.includes('paused') || dialog.innerText.includes('Tiếp tục xem'))) {
                            dialogFound = true;
                            console.log('[Proxify] Phát hiện popup tạm dừng video!');
                            
                            // 1. Try to click the "Yes / Có" button
                            const buttons = dialog.querySelectorAll('button, yt-button-shape, .yt-spec-button-shape-next');
                            buttons.forEach(btn => {
                                if (btn.innerText.includes('Có') || btn.innerText.includes('Yes')) {
                                    btn.click();
                                }
                            });
                            
                            // 2. Force close/remove the dialog
                            if (typeof dialog.close === 'function') {
                                dialog.close();
                            }
                            dialog.remove(); // Nuke it from DOM
                        }
                    });

                    // 3. Force video to play if it was paused
                    if (dialogFound) {
                        const video = document.querySelector('video');
                        if (video && video.paused) {
                            video.play().catch(e => console.error(e));
                            console.log('[Proxify] Đã ép video phát tiếp!');
                        }
                        
                        const playBtn = document.querySelector('.ytp-play-button.ytp-button');
                        const isPaused = document.querySelector('.html5-video-player.paused-mode');
                        if (isPaused && playBtn) {
                            playBtn.click();
                        }
                    }
                }, 1000);
            })();
            </script>
            """
            if "</body>" in new_body:
                new_body = new_body.replace("</body>", f"{script}</body>")
                modified = True
            elif "</body>" in body and not modified:
                new_body = body.replace("</body>", f"{script}</body>")
                modified = True

        if modified:
            flow.response.content = new_body.encode("utf-8")
            self.logger.info("🔪 [AD STRIPPED / INJECTED] Modified youtube response")
