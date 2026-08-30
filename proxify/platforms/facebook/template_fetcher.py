"""
Facebook Template Fetcher — Auto-fresh GraphQL templates via Playwright
========================================================================
Opens a headless Chromium, injects cookies from the proxy database,
navigates to the target Facebook Group, and intercepts the first
GraphQL feed request to extract a fresh template (fb_dtsg, lsd,
doc_id, headers, form_data).

This eliminates the need for users to manually browse Facebook
to "capture" a request template.
"""

import asyncio
import json
import logging
from typing import Optional
from urllib.parse import parse_qs

logger = logging.getLogger("proxify.facebook.template_fetcher")

# Timeout for waiting for the GraphQL request to appear
INTERCEPT_TIMEOUT = 30  # seconds
PAGE_LOAD_TIMEOUT = 20_000  # ms for Playwright


async def _get_fb_cookies_from_db() -> tuple[list[dict], str]:
    """
    Extract Facebook cookies and user-agent, checking user-provided config first.
    Returns (cookies_in_playwright_format, user_agent)
    """
    cookie_str = ""
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    # Priority 1: User-provided cookie passed via environment variable
    import os
    cookie_str = os.environ.get("PROXIFY_FB_COOKIE", "")
    env_ua = os.environ.get("PROXIFY_FB_UA", "")
    if env_ua:
        user_agent = env_ua
    
    if cookie_str:
        logger.info("Using user-provided cookie from env for Playwright")

    if not cookie_str:
        # Priority 2: Database (latest intercepted request)
        try:
            from proxify.platforms.facebook.database import fb_db
            with fb_db.pool.cursor(dict_cursor=True) as cur:
                cur.execute(
                    "SELECT request_headers FROM public.requests "
                    "WHERE domain LIKE '%facebook.com%' "
                    "AND request_headers ILIKE '%c_user=%' "
                    "AND request_headers ILIKE '%xs=%' "
                    "ORDER BY timestamp_epoch DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row and row["request_headers"]:
                    import json
                    headers = json.loads(row["request_headers"])
                    cookie_str = headers.get("cookie", "") or headers.get("Cookie", "")
                    db_ua = headers.get("user-agent", "") or headers.get("User-Agent", "")
                    if db_ua:
                        user_agent = db_ua
                    if cookie_str:
                        logger.info("Using cookie from intercepted database requests")
        except Exception as e:
            logger.warning(f"Failed to read cookie from DB: {e}")

    if not cookie_str:
        # Fallback to saved tokens.json cookie
        try:
            from pathlib import Path
            import json
            token_file = Path(__file__).parent / "tokens.json"
            if token_file.exists():
                tokens = json.loads(token_file.read_text(encoding="utf-8"))
                cookie_str = tokens.get("cookie", "")
                if cookie_str:
                    logger.info("Using cookie from tokens.json fallback")
        except Exception as e:
            logger.warning(f"Failed to read cookie from tokens.json: {e}")

    if not cookie_str:
        return [], user_agent

    cookies = []
    separator = "," if "," in cookie_str and ";" not in cookie_str else ";"
    for pair in cookie_str.split(separator):
        if "=" in pair:
            k, v = pair.strip().split("=", 1)
            cookies.append({
                "name": k.strip(),
                "value": v.strip(),
                "domain": ".facebook.com",
                "path": "/",
            })
    return cookies, user_agent

async def fetch_fresh_template(group_id: str) -> Optional[dict]:
    """
    Use Playwright to navigate to a Facebook Group page and intercept
    the first GraphQL feed request to build a fresh template.

    Returns a dict with keys: {headers, form_data, feed, comment}
    or None if the template could not be captured.
    """
    from playwright.async_api import async_playwright

    cookies, user_agent = await _get_fb_cookies_from_db()
    if not cookies:
        logger.error("No Facebook cookies found. "
                      "Please paste your cookie in the Facebook Extractor UI.")
        return None

    logger.info(f"🎭 Launching Playwright to fetch fresh template for group {group_id}")

    captured_template = {}
    capture_event = asyncio.Event()

    def _on_request(request):
        """Intercept GraphQL requests to capture the template."""
        nonlocal captured_template

        if capture_event.is_set():
            return

        url = request.url
        if "/api/graphql" not in url:
            return

        try:
            post_data = request.post_data
            if not post_data:
                return

            # Parse form data
            parsed = parse_qs(post_data, keep_blank_values=True)
            # Flatten single-value lists
            form_data = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}

            friendly_name = form_data.get("fb_api_req_friendly_name", "")

            # We only want the feed query
            if "GroupsCometFeed" not in friendly_name:
                return

            if "fb_dtsg" not in form_data:
                return

            # Extract headers — strip anything that reveals Playwright/automation
            _skip_headers = {
                "content-length", "accept-encoding", "host",
                "connection", "transfer-encoding",
                # sec-ch-ua* headers from Playwright contain "HeadlessChrome"
                # which is the #1 bot detection signal. curl_cffi will
                # auto-generate correct values based on impersonate target.
                "sec-ch-ua", "sec-ch-ua-full-version-list",
                "sec-ch-ua-mobile", "sec-ch-ua-model",
                "sec-ch-ua-platform", "sec-ch-ua-platform-version",
                "sec-ch-prefers-color-scheme",
                # Automation-revealing metadata
                "x-fb-friendly-name", "x-asbd-id", "x-fb-lsd",
            }
            headers = {}
            for k, v in request.headers.items():
                k_lower = k.lower()
                if k_lower.startswith(":") or k_lower in _skip_headers:
                    continue
                headers[k_lower] = v

            captured_template["feed"] = {
                "headers": headers,
                "form_data": form_data,
            }
            # Also store top-level for backward compatibility
            captured_template["headers"] = headers
            captured_template["form_data"] = form_data

            logger.info(
                f"✅ Captured fresh feed template! "
                f"friendly_name={friendly_name}, "
                f"doc_id={form_data.get('doc_id', 'N/A')}"
            )
            capture_event.set()

        except Exception as e:
            logger.debug(f"Error parsing request: {e}")

    def _on_comment_request(request):
        """Also try to capture comment template if it appears."""
        nonlocal captured_template

        url = request.url
        if "/api/graphql" not in url:
            return

        try:
            post_data = request.post_data
            if not post_data:
                return

            parsed = parse_qs(post_data, keep_blank_values=True)
            form_data = {k: v[0] if len(v) == 1 else v for k, v in parsed.items()}
            friendly_name = form_data.get("fb_api_req_friendly_name", "")

            if "fb_dtsg" not in form_data:
                return

            _skip_headers = {
                "content-length", "accept-encoding", "host",
                "connection", "transfer-encoding",
                "sec-ch-ua", "sec-ch-ua-full-version-list",
                "sec-ch-ua-mobile", "sec-ch-ua-model",
                "sec-ch-ua-platform", "sec-ch-ua-platform-version",
                "sec-ch-prefers-color-scheme",
                "x-fb-friendly-name", "x-asbd-id", "x-fb-lsd",
            }
            headers = {}
            for k, v in request.headers.items():
                k_lower = k.lower()
                if k_lower.startswith(":") or k_lower in _skip_headers:
                    continue
                headers[k_lower] = v

            if "comment" in friendly_name.lower() or "ufi" in friendly_name.lower():
                if "repl" in friendly_name.lower():
                    captured_template["reply"] = {
                        "headers": headers,
                        "form_data": form_data,
                    }
                    logger.info(f"✅ Captured fresh reply template! ({friendly_name})")
                else:
                    captured_template["comment"] = {
                        "headers": headers,
                        "form_data": form_data,
                    }
                    logger.info(f"✅ Captured fresh comment template! ({friendly_name})")
        except Exception:
            pass

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=user_agent,
                ignore_https_errors=True,
                extra_http_headers={
                    "sec-ch-ua-platform": '"Windows"',
                    "accept-language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
                }
            )
            # Spoof navigator.platform to prevent Facebook OS mismatch detection
            await context.add_init_script("Object.defineProperty(navigator, 'platform', {get: () => 'Win32'})")

            # Inject cookies from proxy database
            await context.add_cookies(cookies)
            logger.info(f"🍪 Injected {len(cookies)} cookies into Playwright context")

            page = await context.new_page()

            # Register interceptors
            page.on("request", _on_request)
            page.on("request", _on_comment_request)

            # Navigate to the group (Force CHRONOLOGICAL sorting to ensure we crawl from newest to oldest)
            group_url = f"https://www.facebook.com/groups/{group_id}?sorting_setting=CHRONOLOGICAL"
            logger.info(f"🌐 Navigating to {group_url}")

            try:
                await page.goto(
                    group_url,
                    wait_until="domcontentloaded",
                    timeout=PAGE_LOAD_TIMEOUT,
                )
            except Exception as e:
                logger.warning(f"Page load may have timed out (continuing): {e}")

            # Check if we got redirected to login
            current_url = page.url
            if "/login" in current_url or "/checkpoint" in current_url:
                logger.error(
                    "❌ Facebook redirected to login page. "
                    "Cookies may be expired. Please browse Facebook "
                    "through Proxify to refresh cookies."
                )
                try:
                    await page.screenshot(path="/app/scratchs/fb_redirect.png")
                    logger.info("📸 Saved screenshot of login redirect to /app/scratchs/fb_redirect.png")
                except:
                    pass
                await browser.close()
                return None

            scroll_task = None
            # Wait for the feed GraphQL request
            if not capture_event.is_set():
                logger.info("⏳ Waiting for GraphQL feed request...")
                
                async def _scroll_loop():
                    while not capture_event.is_set():
                        try:
                            # Small, smooth scrolls to reliably trigger IntersectionObservers
                            await page.evaluate("window.scrollBy(0, 500)")
                            await page.keyboard.press("PageDown")
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            logger.debug(f"Scroll loop interrupted: {e}")
                            break
                            
                scroll_task = asyncio.create_task(_scroll_loop())

            # Wait for capture with timeout
            try:
                await asyncio.wait_for(
                    capture_event.wait(),
                    timeout=INTERCEPT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                if scroll_task and not scroll_task.done():
                    scroll_task.cancel()
                    
                logger.error(
                    f"❌ Timed out after {INTERCEPT_TIMEOUT}s waiting for "
                    f"GraphQL feed request. The group page may not have loaded."
                )
                # Take a screenshot for debugging
                try:
                    screenshot_path = "/tmp/fb_template_debug.png"
                    await page.screenshot(path=screenshot_path)
                    logger.info(f"📸 Debug screenshot saved to {screenshot_path}")
                except Exception:
                    pass
                await browser.close()
                return None
            
            # Success path cleanup
            if scroll_task and not scroll_task.done():
                scroll_task.cancel()

            # Give a moment for feed
            await asyncio.sleep(1)

            # Try to trigger a comment fetch to capture comment template
            if "comment" not in captured_template:
                logger.info("⏳ Attempting to trigger comment template fetch by clicking 'Xem thêm bình luận' or similar...")
                try:
                    import re
                    # Wait for at least one "bình luận" or "comment" text to appear on screen
                    loc = page.locator("text-matches('(?i).*(bình luận|comment).*')").first
                    try:
                        await loc.wait_for(timeout=5000)
                    except:
                        pass
                    
                    locators = [
                        "span:text-matches('(?i).*bình luận.*')",
                        "span:text-matches('(?i).*comment.*')",
                        "div[role='button']:text-matches('(?i).*bình luận.*')",
                        "div[role='button']:text-matches('(?i).*comment.*')",
                    ]
                    for loc_str in locators:
                        btn = page.locator(loc_str).first
                        if await btn.count() > 0:
                            await btn.click()
                            logger.info(f"👉 Clicked: {loc_str}")
                            await asyncio.sleep(3)
                            break
                except Exception as e:
                    logger.warning(f"Could not click to fetch comments: {e}")

            # We do NOT extract cookies here anymore.
            # Cookies are sensitive and must be managed by the user via LocalStorage.
            # Storing them in tokens.json on the server is a security risk.

            # Save the template to file for fallback use
            token_file = __import__("pathlib").Path(__file__).parent / "tokens.json"
            try:
                token_file.write_text(
                    json.dumps(captured_template, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                logger.info(f"💾 Fresh template saved to {token_file}")
            except Exception as e:
                logger.warning(f"Could not save template to file: {e}")

            await browser.close()
            logger.info("🎭 Playwright browser closed")

            return captured_template

    except Exception as e:
        logger.error(f"❌ Playwright error: {e}")
        return None
