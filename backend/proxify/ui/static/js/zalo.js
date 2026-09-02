// ── State ──
let selectedGroupId = null;

// ── Toast Notification ──
function showToast(msg, type = '') {
    const toast = document.getElementById('toast');
    toast.textContent = msg;
    toast.className = 'toast show ' + type;
    setTimeout(() => { toast.className = 'toast'; }, 3000);
}

// ── Stats ──
async function loadStats() {
    try {
        const res = await fetch('/api/zalo/stats');
        const stats = await res.json();
        document.getElementById('statGroups').textContent = stats.groups || 0;
        document.getElementById('statUsers').textContent = stats.users || 0;
        document.getElementById('statMemberships').textContent = stats.memberships || 0;
    } catch (e) {
        console.error('Failed to load stats', e);
    }
}


// ── Scan Jobs ──
async function loadJobs() {
    // Don't overwrite while fetch command is showing progress
    if (fetchInProgress) return;
    try {
        const res = await fetch('/api/zalo/jobs');
        const jobs = await res.json();
        const container = document.getElementById('jobsSection');

        // Hide cancelled jobs, only show active or recently completed
        const activeJobs = jobs.filter(j => j.status !== 'cancelled');

        if (!activeJobs.length) {
            container.innerHTML = '';
            return;
        }

        container.innerHTML = activeJobs.slice(0, 10).map(j => {
            const statusClass = j.status || 'pending';
            const meta = j.status === 'completed'
                ? `${j.members_found || 0} thành viên`
                : j.status === 'error'
                    ? (j.error_message || 'Lỗi').substring(0, 30)
                    : j.status;
            const showCancel = j.status === 'pending' || j.status === 'running';
            const metaHtml = showCancel
                ? `<button class="action-btn" style="height: 22px; font-size: 10px; padding: 0 6px;" onclick="cancelJob(${j.id})">Hủy</button>`
                : `<div class="job-meta">${escHtml(meta)}</div>`;

            // Shorten link for display
            const displayLink = (j.link || '').replace('group_id:', 'GID:');

            return `
                <div class="job-item">
                    <div class="job-status ${statusClass}"></div>
                    <div class="job-link" title="${escHtml(j.link)}">${escHtml(displayLink)}</div>
                    ${metaHtml}
                </div>
            `;
        }).join('');
    } catch (e) {
        console.error('Failed to load jobs', e);
    }
}

async function cancelJob(jobId) {
    if (!confirm('Bạn có chắc muốn hủy job này?')) return;
    try {
        const res = await fetch(`/api/zalo/jobs/${jobId}/cancel`, { method: 'POST' });
        if (!res.ok) throw new Error('Failed to cancel job');
        await loadJobs();
        showToast('Đã hủy job thành công!', 'success');
    } catch (e) {
        showToast('Lỗi khi hủy job', 'error');
    }
}

// ── Group List ──
async function loadGroups() {
    try {
        const search = document.getElementById('groupSearch').value.trim();
        const params = new URLSearchParams();
        if (search) params.set('search', search);

        const res = await fetch(`/api/zalo/groups?${params}`);
        const groups = await res.json();
        const container = document.getElementById('groupList');

        if (!groups.length) {
            container.innerHTML = `
                <div style="padding: 40px; text-align: center; color: var(--text-muted); font-size: 13px;">
                    Chưa có nhóm nào. Hãy dán link nhóm Zalo ở trên để bắt đầu quét!
                </div>
            `;
            return;
        }

        container.innerHTML = groups.map(g => {
            const initial = (g.display_name || '?')[0].toUpperCase();
            const isActive = g.group_id === selectedGroupId ? 'active' : '';
            const avatarContent = g.avatar
                ? `<img src="${escHtml(g.avatar)}" onerror="this.parentElement.textContent='${initial}'">`
                : initial;
            return `
                <div class="group-item ${isActive}" onclick="selectGroup('${escHtml(g.group_id)}')">
                    <div class="group-avatar">${avatarContent}</div>
                    <div class="group-info">
                        <div class="group-name">${escHtml(g.display_name || 'Nhóm không tên')}</div>
                        <div class="group-meta">
                            <span>ID: ${escHtml(g.group_id)}</span>
                        </div>
                    </div>
                    <div class="group-member-count">${g.db_member_count || g.total_member || 0} 👥</div>
                </div>
            `;
        }).join('');
    } catch (e) {
        console.error('Failed to load groups', e);
    }
}

// ── Select Group ──
async function selectGroup(groupId) {
    selectedGroupId = groupId;

    // Highlight in list
    document.querySelectorAll('.group-item').forEach(el => el.classList.remove('active'));
    const active = document.querySelector(`.group-item[onclick*="${groupId}"]`);
    if (active) active.classList.add('active');

    // Show detail panel
    document.getElementById('emptyState').style.display = 'none';
    const detail = document.getElementById('groupDetail');
    detail.style.display = 'flex';

    // Load group info from list data
    try {
        const res = await fetch(`/api/zalo/groups?search=${groupId}`);
        const groups = await res.json();
        const g = groups.find(x => x.group_id === groupId) || {};

        const initial = (g.display_name || '?')[0].toUpperCase();
        const avatarEl = document.getElementById('detailAvatar');
        if (g.avatar) {
            avatarEl.innerHTML = `<img src="${escHtml(g.avatar)}" onerror="this.parentElement.textContent='${initial}'">`;
        } else {
            avatarEl.textContent = initial;
        }

        document.getElementById('detailName').textContent = g.display_name || 'Nhóm không tên';
        document.getElementById('detailMemberCount').textContent = `${g.db_member_count || g.total_member || 0} thành viên`;
        document.getElementById('detailGroupId').textContent = `ID: ${groupId}`;
    } catch (e) {}

    // Load members
    loadMembers();
    loadGroups(); // Refresh list to update active state
}

// ── Load Members ──
async function loadMembers() {
    if (!selectedGroupId) return;

    const search = document.getElementById('memberSearch').value.trim();
    const params = new URLSearchParams();
    if (search) params.set('search', search);

    try {
        const res = await fetch(`/api/zalo/groups/${selectedGroupId}/members?${params}`);
        const members = await res.json();
        const tbody = document.getElementById('memberTableBody');

        document.getElementById('memberCountBadge').textContent = `${members.length} kết quả`;

        if (!members.length) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="5" style="text-align: center; padding: 40px; color: var(--text-muted);">
                        Chưa có thành viên nào được thu thập cho nhóm này.
                    </td>
                </tr>
            `;
            return;
        }

        tbody.innerHTML = members.map((m, idx) => {
            const avatarHtml = m.avatar
                ? `<img src="${escHtml(m.avatar)}" onerror="this.style.display='none'">`
                : '';
            const updatedAt = m.updated_at ? new Date(m.updated_at).toLocaleDateString('vi-VN') : '—';
            return `
                <tr>
                    <td style="color: var(--text-muted); font-family: 'JetBrains Mono', monospace; font-size: 10px;">${idx + 1}</td>
                    <td>
                        <div class="member-name-cell">
                            <div class="member-row-avatar">${avatarHtml}</div>
                            <div>
                                <div class="member-name">${escHtml(m.display_name || 'Ẩn danh')}</div>
                                <div class="member-uid">${escHtml(m.user_id)}</div>
                            </div>
                        </div>
                    </td>
                    <td><span class="member-gid">${escHtml(m.global_id || '—')}</span></td>
                    <td><span class="member-phone">${escHtml(m.phone || '—')}</span></td>
                    <td style="color: var(--text-muted); font-size: 11px;">${updatedAt}</td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        console.error('Failed to load members', e);
    }
}

// ── Export Members ──
function exportMembers(format) {
    if (!selectedGroupId) return;
    window.open(`/api/zalo/groups/${selectedGroupId}/export?format=${format}`, '_blank');
}

// ── Rescan Group ──
let fetchInProgress = false;

async function rescanGroup(groupId) {
    const targetId = groupId || selectedGroupId;
    if (!targetId) return;
    
    const btn = document.querySelector('.group-detail-actions .primary');
    try {
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> Đang gửi...';
        }
        
        const res = await fetch('/api/zalo/commands/fetch_members', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ group_id: targetId })
        });
        const data = await res.json();
        
        if (data.status === 'ok') {
            showToast('Đã gửi lệnh! Chờ Chrome xử lý (~10s)...', 'success');
            showFetchProgress(targetId);
        } else {
            showToast(data.error || 'Lỗi gửi lệnh', 'error');
            if (btn) { btn.disabled = false; btn.innerHTML = '🔄 Lấy toàn bộ thành viên'; }
        }
    } catch (e) {
        showToast('Lỗi kết nối', 'error');
        if (btn) { btn.disabled = false; btn.innerHTML = '🔄 Lấy toàn bộ thành viên'; }
    }
}

function showFetchProgress(groupId) {
    fetchInProgress = true;
    const btn = document.querySelector('.group-detail-actions .primary');
    if (btn) btn.innerHTML = '<span class="spinner"></span> Đang lấy thành viên...';
    
    // Add a visual job item to the jobs section
    const container = document.getElementById('jobsSection');
    const jobEl = document.createElement('div');
    jobEl.className = 'job-item';
    jobEl.id = 'fetchJob_' + groupId;
    jobEl.innerHTML = `
        <div class="job-status running"></div>
        <div class="job-link">🔄 Lấy thành viên GID:${groupId.slice(-8)}</div>
        <div class="job-meta" id="fetchJobMeta_${groupId}">đang chờ...</div>
    `;
    container.prepend(jobEl);
    
    const initialCount = parseInt(document.getElementById('memberCountBadge')?.textContent) || 0;
    let checks = 0;
    const maxChecks = 12;
    const startTime = Date.now();
    
    const metaEl = document.getElementById('fetchJobMeta_' + groupId);
    
    const interval = setInterval(async () => {
        checks++;
        const elapsed = Math.round((Date.now() - startTime) / 1000);
        if (metaEl) metaEl.textContent = `đang xử lý... ${elapsed}s`;
        
        try {
            loadStats();
            const curRes = await fetch(`/api/zalo/groups`);
            const groups = await curRes.json();
            const g = groups.find(x => x.group_id === groupId);
            const newCount = g?.db_member_count || 0;
            
            if (newCount > initialCount || checks >= maxChecks) {
                clearInterval(interval);
                fetchInProgress = false;
                if (btn) { btn.disabled = false; btn.innerHTML = '🔄 Lấy toàn bộ thành viên'; }
                
                // Update job item to completed
                const statusEl = jobEl.querySelector('.job-status');
                if (newCount > initialCount) {
                    if (statusEl) statusEl.className = 'job-status completed';
                    if (metaEl) metaEl.textContent = `✅ ${newCount} thành viên (+${newCount - initialCount})`;
                    showToast(`✅ Đã lấy ${newCount} thành viên!`, 'success');
                } else {
                    if (statusEl) statusEl.className = 'job-status error';
                    if (metaEl) metaEl.textContent = `timeout (${elapsed}s)`;
                    showToast('Hết thời gian chờ. Reload trang Zalo trên Chrome.', 'error');
                }
                
                if (selectedGroupId === groupId) {
                    selectGroup(groupId);
                }
                
                // Auto-remove after 15s
                setTimeout(() => jobEl.remove(), 15000);
            }
        } catch(_) {}
    }, 5000);
}

// ── Helpers ──
function escHtml(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Submit Scan ──
async function submitScan() {
    const input = document.getElementById('scanInput');
    const link = input.value.trim();
    if (!link) {
        showToast('Vui lòng nhập link nhóm hoặc Group ID', 'error');
        return;
    }

    const btn = document.getElementById('scanBtn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Đang gửi...';

    try {
        const body = link.match(/^\d+$/) ? { group_id: link } : { link: link };
        const res = await fetch('/api/zalo/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await res.json();

        if (data.status === 'ok') {
            showToast('Đã gửi lệnh quét! Bot sẽ xử lý...', 'info');
            input.value = '';
            setTimeout(loadJobs, 1000);
        } else {
            showToast(data.error || 'Lỗi gửi lệnh quét', 'error');
        }
    } catch (e) {
        showToast('Lỗi kết nối server', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🔍 Quét';
    }
}

// ── Bot Management ──
let botRunning = false;
let lastPendingJobTime = null;

async function checkBotStatus() {
    try {
        // Detect bot activity: if there are running jobs, bot is active
        const res = await fetch('/api/zalo/jobs');
        const jobs = await res.json();
        const hasRunning = jobs.some(j => j.status === 'running');
        const hasPending = jobs.some(j => j.status === 'pending');

        if (hasRunning) {
            botRunning = true;
        } else if (hasPending) {
            // If jobs are pending for more than 30s, bot is probably not running
            if (!lastPendingJobTime) lastPendingJobTime = Date.now();
            botRunning = (Date.now() - lastPendingJobTime) < 30000;
        } else {
            lastPendingJobTime = null;
            // Keep previous state if no jobs
        }

        // Also try the API status (works when running on host, not in docker)
        try {
            const statusRes = await fetch('/api/zalo/bot/status');
            const statusData = await statusRes.json();
            if (statusData.running) botRunning = true;
        } catch(_) {}

        updateBotUI();
    } catch (e) {
        // Silently ignore
    }
}

function updateBotUI() {
    const btn = document.getElementById('botToggleBtn');
    const label = document.getElementById('botLabel');
    if (!btn || !label) return;

    if (botRunning) {
        btn.classList.add('running');
        label.textContent = 'Bot: Đang chạy';
    } else {
        btn.classList.remove('running');
        label.textContent = 'Bot: Tắt';
    }
}

async function toggleBot() {
    if (botRunning) {
        // Try to stop via API
        try {
            await fetch('/api/zalo/bot/stop', { method: 'POST' });
            botRunning = false;
            updateBotUI();
            showToast('Đã gửi lệnh dừng bot');
        } catch(_) {}
        return;
    }

    // Try to start via API first
    try {
        const res = await fetch('/api/zalo/bot/start', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'ok' && data.running) {
            botRunning = true;
            updateBotUI();
            showToast('Bot đã khởi động! Cửa sổ trình duyệt sẽ mở ra.', 'info');
            return;
        }
    } catch(_) {}

    // If API start failed (e.g. running in Docker), show instructions
    showBotInstructions();
}

function showBotInstructions() {
    // Create modal overlay
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:1000;display:flex;align-items:center;justify-content:center;backdrop-filter:blur(4px);';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };

    const modal = document.createElement('div');
    modal.style.cssText = 'background:var(--bg-card,#1a1a2e);border:1px solid var(--border,#333);border-radius:16px;padding:32px;max-width:520px;width:90%;color:#e0e0e0;box-shadow:0 20px 60px rgba(0,0,0,0.5);';
    modal.innerHTML = `
        <h3 style="margin:0 0 16px;font-size:18px;color:#fff;">🤖 Khởi động Zalo Bot</h3>
        <p style="margin:0 0 12px;font-size:13px;color:#aaa;line-height:1.6;">
            Bot cần chạy <b>trên máy host</b> (không phải trong Docker) vì nó cần mở cửa sổ trình duyệt thật để đăng nhập Zalo.
        </p>
        <p style="margin:0 0 8px;font-size:12px;color:#888;">Cách 1: Double-click file:</p>
        <div style="background:rgba(0,0,0,0.4);border:1px solid #333;border-radius:8px;padding:12px;font-family:'JetBrains Mono',monospace;font-size:12px;color:#4fc3f7;margin-bottom:12px;cursor:pointer;" onclick="navigator.clipboard.writeText('start_zalo_bot.bat');this.style.borderColor='#4caf50';this.querySelector('span').textContent='✅ Đã copy!'">
            📁 start_zalo_bot.bat <span style="float:right;color:#666;">📋 Click để copy</span>
        </div>
        <p style="margin:0 0 8px;font-size:12px;color:#888;">Cách 2: Chạy lệnh trong terminal:</p>
        <div style="background:rgba(0,0,0,0.4);border:1px solid #333;border-radius:8px;padding:12px;font-family:'JetBrains Mono',monospace;font-size:12px;color:#4fc3f7;cursor:pointer;" onclick="navigator.clipboard.writeText('$env:DB_DSN=\\'postgresql://proxify_user:proxify_pass@localhost:5432/proxify_db\\'; python -m proxify.platforms.zalo.bot');this.style.borderColor='#4caf50';this.querySelector('span').textContent='✅ Đã copy!'">
            python -m proxify.platforms.zalo.bot <span style="float:right;color:#666;">📋 Click để copy</span>
        </div>
        <div style="margin-top:20px;text-align:right;">
            <button onclick="this.closest('div[style*=fixed]').remove()" style="background:var(--zalo-blue,#0068ff);border:none;color:white;padding:8px 20px;border-radius:8px;font-size:13px;cursor:pointer;font-weight:600;">Đã hiểu</button>
        </div>
    `;
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
}

// ── Polling ──
let refreshInterval = null;

function startPolling() {
    // Immediate load
    loadStats();
    loadGroups();
    loadJobs();
    checkBotStatus();

    // Periodic refresh
    refreshInterval = setInterval(() => {
        loadStats();
        loadGroups();
        loadJobs();
        checkBotStatus();
    }, 5000);
}

// ── Init ──
startPolling();
