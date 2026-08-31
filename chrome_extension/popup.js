document.getElementById('getCookieBtn').addEventListener('click', async () => {
    const status = document.getElementById('status');
    const btn = document.getElementById('getCookieBtn');
    
    btn.disabled = true;
    btn.style.opacity = '0.5';
    status.innerText = "Đang lấy cookie...";
    status.style.color = "white";
    
    try {
        // Đọc toàn bộ cookie của facebook.com
        const cookies = await chrome.cookies.getAll({ domain: "facebook.com" });
        if (cookies.length === 0) {
            status.innerText = "❌ Chưa đăng nhập Facebook!";
            status.style.color = "#ef4444";
            btn.disabled = false;
            btn.style.opacity = '1';
            return;
        }
        // Build the cookie string
        let cookieStr = cookies.map(c => `${c.name}=${c.value}`).join("; ");
        const userAgent = navigator.userAgent;
        
        status.innerText = "Đang trích xuất fb_dtsg từ trang hiện tại...";
        let fb_dtsg = "";
        let lsd = "";
        let syntheticTemplate = null;
        
        try {
            let targetTabId = null;
            
            // First check active tab
            const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
            if (activeTab && activeTab.url.includes("facebook.com")) {
                targetTabId = activeTab.id;
            } else {
                // Fallback: search all tabs for facebook.com
                const allTabs = await chrome.tabs.query({ url: "*://*.facebook.com/*" });
                if (allTabs && allTabs.length > 0) {
                    targetTabId = allTabs[0].id;
                }
            }

            if (targetTabId) {
                const results = await chrome.scripting.executeScript({
                    target: { tabId: targetTabId },
                    world: "MAIN",
                    func: () => {
                        let res = { dtsg: "", lsd: "", user: "", sd: null };
                        try {
                            const dtsgObj = require("DTSGInitialData");
                            if (dtsgObj && dtsgObj.token) res.dtsg = dtsgObj.token;
                        } catch(e){}
                        
                        try {
                            const lsdObj = require("LSD");
                            if (lsdObj && lsdObj.token) res.lsd = lsdObj.token;
                        } catch(e){}
                        
                        try { res.user = require("CurrentUserInitialData").USER_ID; } catch(e){}
                        
                        try {
                            const sd = require("SiteData");
                            res.sd = {
                                rev: String(sd.revision || ""), 
                                hsi: String(sd.hsi || ""), 
                                spin_r: String(sd.__spin_r || ""),
                                spin_b: String(sd.__spin_b || ""), 
                                spin_t: String(sd.__spin_t || ""), 
                                hs: String(sd.haste_session || ""),
                                dpr: String(sd.pr || "1"), 
                                ccg: String(sd.connectionClass || "GOOD")
                            };
                        } catch(e){}
                        
                        return res;
                    }
                });
                
                
                if (results && results[0] && results[0].result) {
                    let r = results[0].result;
                    fb_dtsg = r.dtsg || "";
                    lsd = r.lsd || "";
                    
                    let sum = 0;
                    for (let i = 0; i < fb_dtsg.length; i++) {
                        sum += fb_dtsg.charCodeAt(i);
                    }
                    let jazoest = "2" + sum;
                    
                }
            } else {
                console.warn("No Facebook tab found anywhere. Cannot extract fb_dtsg via scripting.");
                status.innerText += "\n⚠️ Không tìm thấy tab Facebook nào đang mở! Vui lòng mở 1 tab Facebook.";
            }
        } catch (e) {
            console.error("Failed to execute script for fb_dtsg:", e);
        }
        
        try {
            // Gửi qua API của Proxify (mặc định port 8888)
            status.innerText = "Đang gửi vào Proxify...";
            
            // First send cookie
            const res = await fetch("http://127.0.0.1:8888/api/facebook/cookie", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ cookie: cookieStr, user_agent: userAgent, fb_dtsg: fb_dtsg, lsd: lsd })
            });
            const data = await res.json();
            
            if (data.status === "ok") {
                status.innerText = "✅ HOÀN TẤT!\nĐã lưu Cookie thành công.\n(Lưu ý: Nếu bị lỗi GraphQL, hãy mở 1 Nhóm Facebook bất kỳ và cuộn vài bài viết để Extension tự động cập nhật Template).";
                status.style.color = "#10b981";
            } else {
                status.innerText = "❌ Lỗi: " + JSON.stringify(data);
                status.style.color = "#ef4444";
            }
        } catch (e) {
            console.error("Fetch error:", e);
            status.innerText = "❌ Lỗi kết nối đến Proxify (" + e.message + "). Hãy đảm bảo Server đang chạy ở port 8888.";
            status.style.color = "#ef4444";
        }
    } catch (e) {
        status.innerText = "❌ Lỗi xử lý Extension";
        status.style.color = "#ef4444";
        console.error(e);
    }
    
    btn.disabled = false;
    btn.style.opacity = '1';
});
