"""
Zalo Bot — Scan Worker

Polls the `zalo.scan_jobs` table for pending scan jobs submitted
via the Zalo Extractor web UI, then uses Playwright to navigate to each
Zalo group link through the MITM proxy.

The MITM proxy's JS hooks automatically extract group members and push
data into PostgreSQL (schema: zalo).

Usage:
    1. Start the proxy:   python -m proxify
    2. Start the bot:     python -m proxify.platforms.zalo.bot
    3. Open the UI:       http://localhost:8888/zalo
    4. Paste a group link and click "Quét"!
"""

import asyncio
import logging
import os
import signal
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("zalo_bot")

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

proxy_port = os.environ.get("PROXY_PORT", "8080")
PROXY_SERVER = f"http://127.0.0.1:{proxy_port}"
USER_DATA_DIR = str(PROJECT_ROOT / "zalo_browser_data")
POLL_INTERVAL = 3   # seconds between checking for new jobs
EXTRACT_WAIT = 20   # seconds to wait for JS hooks to extract data per group


async def ensure_logged_in(page):
    """Navigate to Zalo Web and ensure the user is logged in."""
    await page.goto("https://chat.zalo.me/", wait_until="domcontentloaded", timeout=60000)
    
    # Unregister Service Workers to prevent them from serving old, un-injected JS files
    await page.evaluate('''() => {
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.getRegistrations().then(function(registrations) {
                for(let registration of registrations) {
                    registration.unregister();
                }
            });
        }
    }''')
    
    # Reload to ensure fresh scripts are fetched through the proxy
    await page.reload(wait_until="domcontentloaded", timeout=60000)
    
    logger.info("⏳ Kiểm tra trạng thái đăng nhập Zalo...")
    await page.wait_for_timeout(5000)

    attempt = 0
    while True:
        title = await page.title()
        login_visible = await page.locator(".login-content").count() > 0
        if "Đăng nhập" not in title and not login_visible:
            logger.info("✅ Đã đăng nhập Zalo Web thành công!")
            return True
        attempt += 1
        if attempt == 1:
            logger.info("⏳ Chưa đăng nhập. Vui lòng quét mã QR trên cửa sổ trình duyệt...")
        if attempt % 6 == 0:
            logger.info("⏳ Vẫn đang chờ đăng nhập...")
        await page.wait_for_timeout(5000)


async def process_job(page, job, zalo_db):
    """Process a single scan job: navigate to the link and wait for extraction."""
    job_id = job["id"]
    link = job["link"]

    logger.info(f"[Job #{job_id}] 🔍 Bắt đầu quét: {link}")
    zalo_db.jobs.update(job_id, status="running", started_at="CURRENT_TIMESTAMP")

    try:
        if link.startswith("group_id:"):
            target_gid = link.split(":")[1]
            logger.info(f"[Job #{job_id}] Đang ép tải dữ liệu thành viên cho group ID: {target_gid}")
            
            # Đảm bảo đang ở trang chat.zalo.me
            if "chat.zalo.me" not in page.url:
                await page.goto("https://chat.zalo.me/", wait_until="domcontentloaded", timeout=30000)
            
            # Đợi một chút cho Webpack sẵn sàng
            await page.wait_for_timeout(2000)
            
            # Gọi trực tiếp hàm fetchFullGroupInfo đã được inject bởi proxy
            hook_exists = await page.evaluate("typeof window.__proxify_fetchFullGroupInfo === 'function'")
            
            if not hook_exists:
                logger.info(f"[Job #{job_id}] ⚠️ JS hooks chưa inject — đang reload trang...")
                await page.reload(wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(5000)
                hook_exists = await page.evaluate("typeof window.__proxify_fetchFullGroupInfo === 'function'")
            
            if hook_exists:
                await page.evaluate(f"""
                    window.__proxify_fetchFullGroupInfo('{target_gid}');
                """)
            else:
                logger.warning(f"[Job #{job_id}] ❌ JS hooks vẫn không tồn tại sau reload!")
            
            logger.info(f"[Job #{job_id}] ⏳ Đang chờ JS hooks trích xuất dữ liệu ({EXTRACT_WAIT}s)...")
            await page.wait_for_timeout(EXTRACT_WAIT * 1000)
            
        else:
            await page.goto(link, wait_until="domcontentloaded", timeout=30000)
            logger.info(f"[Job #{job_id}] Đang mở link nhóm...")

            try:
                html = await page.content()
                with open("join_debug.html", "w", encoding="utf-8") as f:
                    f.write(html)
                await page.screenshot(path="join_debug.png")
                logger.info(f"[Job #{job_id}] Đã lưu HTML và ảnh chụp màn hình để debug.")
            except Exception as e:
                logger.warning(f"Lỗi khi chụp màn hình debug: {e}")

            # ── Tự động bấm nút "Dùng bản Web" hoặc "Tham gia chat" nếu đang ở trang Landing ──
            try:
                clicked = False
                
                # Kiểm tra xem có bị dính Captcha không
                if await page.locator("text='Kiểm tra bảo mật'").count() > 0 or await page.locator("text='Xác Minh'").count() > 0:
                    logger.warning(f"[Job #{job_id}] ⚠️ Zalo yêu cầu xác minh Captcha!")
                    logger.warning(f"[Job #{job_id}] 👉 VUI LÒNG TỰ BẤM NÚT 'XÁC MINH' TRÊN CỬA SỔ TRÌNH DUYỆT CỦA BOT ĐỂ ĐI TIẾP (Chờ 60s)...")
                    try:
                        # Chờ cho đến khi chuyển hướng sang chat.zalo.me hoặc nhóm
                        await page.wait_for_url("**/*chat.zalo.me*", timeout=60000)
                        logger.info(f"[Job #{job_id}] Đã qua được Captcha và vào Zalo Web!")
                        clicked = True
                    except Exception:
                        logger.error(f"[Job #{job_id}] Hết thời gian chờ Captcha!")
                
                # 1. Tìm thẻ <a> có chứa link tới chat.zalo.me
                chat_link = page.locator("a[href*='chat.zalo.me']").first
                if await chat_link.count() > 0:
                    href = await chat_link.get_attribute("href")
                    if href and href != "#" and not href.startswith("javascript"):
                        logger.info(f"[Job #{job_id}] Đã tìm thấy link chat.zalo.me, đang chuyển hướng...")
                        await page.goto(href, wait_until="domcontentloaded", timeout=15000)
                        clicked = True
                
                # 2. Nếu không có, thử tìm qua text
                if not clicked:
                    for text in ["Dùng bản Web", "Dùng Zalo Web", "Mở Zalo Web", "Tham gia chat", "Tham gia nhóm", "Mở bằng Zalo Web", "Tham gia cộng đồng"]:
                        btn = page.locator(f"text='{text}'").first
                        if await btn.count() > 0:
                            tag = await btn.evaluate("el => el.tagName.toLowerCase()")
                            if tag == 'a':
                                href = await btn.get_attribute("href")
                                if href and href != "#" and not href.startswith("javascript"):
                                    await page.goto(href, wait_until="domcontentloaded", timeout=15000)
                                    logger.info(f"[Job #{job_id}] Đã điều hướng tới: {href}")
                                    clicked = True
                                    break
                            await btn.click(timeout=3000)
                            logger.info(f"[Job #{job_id}] Đã bấm nút '{text}' để vào nhóm!")
                            clicked = True
                            break

                if not clicked:
                    logger.info(f"[Job #{job_id}] Không tìm thấy nút (có thể đã tự động chuyển hoặc đang ở sẵn Zalo Web).")
            except Exception as e:
                logger.warning(f"[Job #{job_id}] Lỗi khi bấm nút: {e}")

            logger.info(f"[Job #{job_id}] ⏳ Đang chờ JS hooks trích xuất dữ liệu ({EXTRACT_WAIT}s)...")
            await page.wait_for_timeout(EXTRACT_WAIT * 1000)

        # Try to extract group ID
        group_id = None
        is_direct_id = link.startswith("group_id:")
        if is_direct_id:
            group_id = link.split(":")[1]
        
        if not group_id:
            try:
                group_id = await page.evaluate("""
                    () => {
                        const g = window.__zalo_groupRuntime;
                        if (g && g.currentGroupId) return g.currentGroupId;
                        const url = window.location.href;
                        const match = url.match(/g(\\d+)/);
                        if (match) return match[1];
                        return null;
                    }
                """)
            except Exception:
                pass

        # Nếu là link scan và tìm thấy group_id sau khi vào nhóm, ép tải thành viên
        if group_id and not is_direct_id:
            logger.info(f"[Job #{job_id}] Đã vào được nhóm, bắt đầu ép tải thành viên cho group ID: {group_id}")
            await page.evaluate(f"""
                if (window.__proxify_fetchFullGroupInfo) {{
                    window.__proxify_fetchFullGroupInfo('{group_id}');
                }}
            """)
            await page.wait_for_timeout(EXTRACT_WAIT * 1000)

        # Count members from DB
        members_found = 0
        if group_id:
            try:
                with zalo_db.pool.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(*) FROM zalo.group_members WHERE group_id = %s",
                        (group_id,)
                    )
                    members_found = cur.fetchone()[0]
            except Exception as e:
                logger.error(f"[Job #{job_id}] Lỗi khi đếm thành viên từ DB: {e}")

        zalo_db.jobs.update(
            job_id,
            status="completed",
            group_id=group_id,
            members_found=members_found,
            completed_at="CURRENT_TIMESTAMP"
        )
        logger.info(f"[Job #{job_id}] ✅ Hoàn thành! (Group: {group_id}, Members: {members_found})")

    except Exception as e:
        error_msg = str(e)[:500]
        zalo_db.jobs.update(
            job_id,
            status="error",
            error_message=error_msg,
            completed_at="CURRENT_TIMESTAMP"
        )
        logger.error(f"[Job #{job_id}] ❌ Lỗi: {error_msg}")


async def main():
    from cloakbrowser import launch_persistent_context_async

    try:
        from proxify.platforms.zalo import zalo_db
    except Exception as e:
        logger.error(f"Không thể import zalo_db: {e}")
        logger.error("Hãy chắc chắn bạn đang chạy từ thư mục gốc của dự án.")
        return

    logger.info("=" * 60)
    logger.info("  🤖 Zalo Bot — Scan Worker (CloakBrowser Stealth)")
    logger.info(f"  📡 Proxy: {PROXY_SERVER}")
    logger.info(f"  ⏱️  Poll interval: {POLL_INTERVAL}s")
    logger.info(f"  ⏳ Extract wait: {EXTRACT_WAIT}s per group")
    logger.info("=" * 60)

    logger.info("🌐 Đang khởi động trình duyệt CloakBrowser...")
    context = await launch_persistent_context_async(
        user_data_dir=USER_DATA_DIR,
        viewport={"width": 1280, "height": 800},
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--ignore-certificate-errors",
            "--disable-cache",
            "--disable-application-cache",
            "--disk-cache-size=1"
        ],
        proxy={"server": PROXY_SERVER},
        ignore_https_errors=True,
    )

    page = await context.new_page()
    
    # Capture console logs to see why JS fetch fails
    page.on("console", lambda msg: logger.info(f"💻 [Browser Console] {msg.type}: {msg.text}"))

    await ensure_logged_in(page)

    logger.info("🔄 Bắt đầu polling scan jobs từ database...")
    logger.info("   Mở http://localhost:8888/zalo để gửi link nhóm cần quét.")

    try:
        while True:
            try:
                pending = zalo_db.jobs.get_pending()
                if pending:
                    logger.info(f"📋 Tìm thấy {len(pending)} job(s) chờ xử lý.")
                    for job in pending:
                        await process_job(page, job, zalo_db)
                        await page.wait_for_timeout(2000)
                await asyncio.sleep(POLL_INTERVAL)
            except Exception as loop_e:
                logger.error(f"Lỗi trong vòng lặp chính (có thể trình duyệt bị đóng): {loop_e}")
                if "TargetClosed" in str(loop_e) or "has been closed" in str(loop_e):
                    logger.error("Trình duyệt đã bị đóng. Dừng bot...")
                    break
                await asyncio.sleep(POLL_INTERVAL)

    except asyncio.CancelledError:
        logger.info("Bot bị hủy.")
    finally:
        logger.info("🛑 Đang đóng trình duyệt...")
        await context.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n🛑 Bot đã dừng.")
