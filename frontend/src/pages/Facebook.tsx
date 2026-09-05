import React, { useState } from 'react';
import { useFacebook } from '../hooks/useFacebook';

export const FacebookPage: React.FC = () => {
    const { 
        crawling, feedCrawling, data, statusText, statusColor, toastMessage, cookie, saveCookie,
        startCrawl, stopCrawl, page, setPage, limit, setLimit, total,
        sort, order, changeSort,
        groups, groupIdFilter, groupNameFilter, selectGroup,
        statusFilter, setStatusFilter,
        selectedPosts, toggleSelection, toggleSelectAll,
        bulkRefresh, bulkCheckStatus, bulkCrawlComments, bulkExportCsv, bulkDelete,
        fetchComments, startDateFilter, setStartDateFilter, endDateFilter, setEndDateFilter,
        crawlPostComments, stopCommentCrawl, commentCrawlProgress, isCommentCrawling } = useFacebook();

    const [groupId, setGroupId] = useState(localStorage.getItem('fb_groupId') || '');
    const [targetType, setTargetType] = useState<'group' | 'profile'>(localStorage.getItem('fb_targetType') as any || 'group');
    const [cookieExpanded, setCookieExpanded] = useState(false);
    const [groupDropdownOpen, setGroupDropdownOpen] = useState(false);
    const [statusDropdownOpen, setStatusDropdownOpen] = useState(false);
    const [groupSearch, setGroupSearch] = useState('');
    const [cookieInput, setCookieInput] = useState(cookie);
    const [fbDtsgInput, setFbDtsgInput] = useState(localStorage.getItem('fb_dtsg') || '');

    // Comment Modal (Lưu theo Session)
    const [modalOpen, setModalOpen] = useState(() => sessionStorage.getItem('fb_modal_open') === 'true');
    const [selectedPost, setSelectedPost] = useState<any>(() => {
        try {
            return JSON.parse(sessionStorage.getItem('fb_selected_post') || 'null');
        } catch (e) {
            return null;
        }
    });
    const [comments, setComments] = useState<any[]>([]);
    const totalPages = Math.max(1, Math.ceil(total / limit));

    // Khôi phục bình luận modal nếu refresh trang khi đang xem và cập nhật live khi đang cào
    React.useEffect(() => {
        if (!modalOpen || !selectedPost) return;
        const pid = selectedPost.post_id || selectedPost.id;
        fetchComments(pid).then(res => {
            if (res && (res.status === 'ok' || res.success)) {
                setComments(res.data || []);
            }
        });

        const isCrawling = commentCrawlProgress[pid]?.status === 'running';
        if (!isCrawling) return;

        const interval = setInterval(() => {
            fetchComments(pid).then(res => {
                if (res && (res.status === 'ok' || res.success)) {
                    setComments(res.data || []);
                }
            });
        }, 2000);

        return () => clearInterval(interval);
    }, [modalOpen, selectedPost, commentCrawlProgress]);

    const handleSaveCookie = () => {
        saveCookie(cookieInput, fbDtsgInput);
    };

    const handleStartCrawl = () => {
        localStorage.setItem('fb_groupId', groupId);
        localStorage.setItem('fb_dtsg', fbDtsgInput);
        localStorage.setItem('fb_targetType', targetType);
        
        startCrawl(groupId, startDateFilter, endDateFilter, targetType);
    };

    const handleGroupFilterChange = (id: string, name: string) => {
        selectGroup(id, name);
        setGroupDropdownOpen(false);
        if (id !== '') {
            setGroupId(id);
            localStorage.setItem('fb_groupId', id);
        }
    };

    const handleStatusFilterChange = (status: string) => {
        setStatusFilter(status);
        setStatusDropdownOpen(false);
        setPage(1);
    };

    const openComments = async (post: any) => {
        setSelectedPost(post);
        setModalOpen(true);
        sessionStorage.setItem('fb_modal_open', 'true');
        sessionStorage.setItem('fb_selected_post', JSON.stringify(post));
        const pid = post.post_id || post.id;
        const res = await fetchComments(pid);
        if (res && (res.status === 'ok' || res.success)) {
            setComments(res.data || []);
        } else {
            setComments([]);
        }
    };

    const closeComments = () => {
        setModalOpen(false);
        setSelectedPost(null);
        sessionStorage.removeItem('fb_modal_open');
        sessionStorage.removeItem('fb_selected_post');
    };

    const handleStartCrawlComments = async (post: any) => {
        if (!post) return;
        const pid = post.post_id || post.id;
        const res: any = await crawlPostComments(pid, post.feedback_id);
        if (res && (res.status === 'ok' || res.success)) {
            setComments(res.data || []);
        }
    };

    // Derived states
    const cookieStatus = cookie ? `✅ ${cookie.length} kí tự` : 'Chưa cài đặt';
    const cookieStatusColor = cookie ? 'var(--green)' : 'var(--text-muted)';
    const allSelected = data.length > 0 && selectedPosts.size === data.length;

    // Filter groups by search
    const filteredGroups = groups.filter(g => 
        (g.group_name || g.group_id || '').toLowerCase().includes(groupSearch.toLowerCase())
    );

    return (
        <div className="main-container">
            {/* LEFT PANEL */}
            <div className="left-panel">
                <h2>Auto Crawl Facebook</h2>

                {/* Cookie Section */}
                <div style={{ marginBottom: '20px', border: '1px solid var(--border)', borderRadius: '10px', overflow: 'hidden' }}>
                    <div 
                        onClick={() => setCookieExpanded(!cookieExpanded)}
                        style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', cursor: 'pointer', background: 'var(--bg-tertiary)', transition: 'all 0.2s' }}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span>🍪</span>
                            <span style={{ fontSize: '14px', fontWeight: 500 }}>Facebook Cookie</span>
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <span style={{ fontSize: '12px', color: cookieStatusColor }}>{cookieStatus}</span>
                            <span style={{ transition: 'transform 0.2s', transform: cookieExpanded ? 'rotate(90deg)' : 'rotate(0deg)' }}>▶</span>
                        </div>
                    </div>
                    {cookieExpanded && (
                        <div style={{ padding: '16px', borderTop: '1px solid var(--border)' }}>
                            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '12px', lineHeight: 1.6 }}>
                                <b>Cách lấy cookie:</b>
                                <ol style={{ margin: '8px 0', paddingLeft: '18px' }}>
                                    <li>Đăng nhập Facebook trên trình duyệt</li>
                                    <li>Nhấn <kbd style={{ background: 'var(--bg-tertiary)', padding: '2px 6px', borderRadius: '4px', fontSize: '11px' }}>F12</kbd> → Tab <b>Application</b> → <b>Cookies</b></li>
                                    <li>Hoặc cài Extension <b>"Cookie Editor"</b> → Export → Header String</li>
                                </ol>
                            </div>
                            <textarea 
                                value={cookieInput}
                                onChange={(e) => setCookieInput(e.target.value)}
                                placeholder={"Paste cookie string ở đây...\nVí dụ: c_user=123456; xs=abc123; fr=xyz..."}
                                style={{ width: '100%', height: '80px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '8px', color: 'var(--text-primary)', padding: '10px', fontSize: '12px', fontFamily: "'JetBrains Mono', monospace", resize: 'vertical', boxSizing: 'border-box' }}
                            />
                            <div style={{ marginTop: '12px' }}>
                                <label style={{ fontSize: '12px', fontWeight: 500, color: 'var(--text-secondary)' }}>fb_dtsg (Tùy chọn - Chống bị đăng xuất):</label>
                                <input 
                                    type="text" 
                                    value={fbDtsgInput}
                                    onChange={(e) => setFbDtsgInput(e.target.value)}
                                    placeholder="Paste fb_dtsg ở đây..."
                                    style={{ width: '100%', marginTop: '4px', background: 'var(--bg-primary)', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--text-primary)', padding: '8px', fontSize: '12px', fontFamily: "'JetBrains Mono', monospace", boxSizing: 'border-box' }}
                                />
                            </div>
                            <div style={{ display: 'flex', gap: '8px', marginTop: '10px', alignItems: 'center' }}>
                                <button 
                                    onClick={handleSaveCookie}
                                    style={{ background: 'var(--accent)', color: 'white', border: 'none', padding: '8px 16px', borderRadius: '6px', fontSize: '13px', cursor: 'pointer', fontWeight: 500 }}
                                >Lưu Cookie</button>
                            </div>
                        </div>
                    )}
                </div>

                {/* Target Type Selector */}
                <div style={{ display: 'flex', gap: '4px', marginBottom: '12px', background: 'var(--bg-tertiary)', borderRadius: '8px', padding: '3px' }}>
                    <button 
                        onClick={() => { setTargetType('group'); localStorage.setItem('fb_targetType', 'group'); }}
                        style={{
                            flex: 1, padding: '8px 12px', border: 'none', borderRadius: '6px', fontSize: '13px', fontWeight: 500, cursor: 'pointer',
                            background: targetType === 'group' ? 'var(--accent)' : 'transparent',
                            color: targetType === 'group' ? 'white' : 'var(--text-secondary)',
                            transition: 'all 0.2s',
                        }}
                    >👥 Nhóm (Group)</button>
                    <button 
                        onClick={() => { setTargetType('profile'); localStorage.setItem('fb_targetType', 'profile'); }}
                        style={{
                            flex: 1, padding: '8px 12px', border: 'none', borderRadius: '6px', fontSize: '13px', fontWeight: 500, cursor: 'pointer',
                            background: targetType === 'profile' ? 'var(--accent)' : 'transparent',
                            color: targetType === 'profile' ? 'white' : 'var(--text-secondary)',
                            transition: 'all 0.2s',
                        }}
                    >👤 Trang cá nhân</button>
                </div>

                {/* Form Controls */}
                <div className="form-grid">
                    <div className="form-group full-width">
                        <label>{targetType === 'profile' ? 'Profile ID / URL' : 'Group ID'}</label>
                        <input 
                            type="text" 
                            value={groupId} 
                            onChange={e => { setGroupId(e.target.value); localStorage.setItem('fb_groupId', e.target.value); }} 
                            placeholder={targetType === 'profile' ? 'Ví dụ: 100012345 hoặc facebook.com/johndoe' : 'Ví dụ: 1234567890'} 
                        />
                    </div>
                    <div className="form-group">
                        <label>Từ ngày</label>
                        <input type="date" value={startDateFilter} onChange={e => { setStartDateFilter(e.target.value); localStorage.setItem('fb_startDate', e.target.value); }} />
                    </div>
                    <div className="form-group">
                        <label>Đến ngày</label>
                        <input type="date" value={endDateFilter} onChange={e => { setEndDateFilter(e.target.value); localStorage.setItem('fb_endDate', e.target.value); }} />
                    </div>
                    <div className="form-group full-width" style={{ marginTop: '8px' }}>
                        {!crawling ? (
                            <button 
                                className="btn-crawl" 
                                style={{ 
                                    width: '100%',
                                    opacity: isCommentCrawling ? 0.5 : 1,
                                    cursor: isCommentCrawling ? 'not-allowed' : 'pointer'
                                }} 
                                disabled={isCommentCrawling}
                                title={isCommentCrawling ? "⚠️ Đang có tiến trình cào bình luận (Comment) đang chạy. Không thể cào bài viết lúc này." : ""}
                                onClick={handleStartCrawl}
                            >
                                {isCommentCrawling ? "⏳ Đang cào bình luận..." : "Bắt đầu thu thập"}
                            </button>
                        ) : (
                            <button className="btn-stop" style={{ width: '100%' }} onClick={stopCrawl}>🛑 Dừng thu thập</button>
                        )}
                    </div>
                </div>

                {statusText && <div className="status-box" style={{ display: 'block', color: statusColor }}>{statusText}</div>}
            </div>

            {/* RIGHT PANEL */}
            <div className="right-panel" style={{ position: 'relative' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 24px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap', zIndex: 20 }}>
                    <h3 style={{ margin: 0, fontSize: '16px', whiteSpace: 'nowrap' }}>Dữ liệu thu thập được</h3>
                    
                    {/* Group Filter Dropdown */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <div style={{ position: 'relative', width: '250px' }}>
                            <input 
                                type="text" 
                                value={groupSearch !== '' ? groupSearch : groupNameFilter} 
                                onChange={e => {
                                    setGroupSearch(e.target.value);
                                    if (e.target.value === '') handleGroupFilterChange('', '');
                                }}
                                onFocus={() => setGroupDropdownOpen(true)}
                                onBlur={() => setTimeout(() => setGroupDropdownOpen(false), 200)}
                                placeholder="Tất cả các nhóm..."
                                style={{ width: '100%', height: '32px', background: 'rgba(0,0,0,0.2)', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--text-primary)', padding: '0 12px', fontSize: '13px', outline: 'none' }}
                            />
                            {groupDropdownOpen && (
                                <div className="filter-dropdown-menu" style={{ display: 'block', width: '100%', maxHeight: '250px', overflowY: 'auto', padding: '4px', top: 'calc(100% + 4px)' }}>
                                    <div className={`filter-dropdown-item ${!groupIdFilter ? 'active' : ''}`} onClick={() => handleGroupFilterChange('', '')}>
                                        Tất cả các nhóm
                                    </div>
                                    {filteredGroups.map((g, i) => (
                                        <div key={i} className={`filter-dropdown-item ${groupIdFilter === g.group_id ? 'active' : ''}`} onClick={() => handleGroupFilterChange(g.group_id, g.group_name)}>
                                            <span>{g.group_name || g.group_id}</span>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                </div>

                {data.length === 0 ? (
                    <div className="empty-state">
                        <div className="icon">🔍</div>
                        <div className="text">Chưa có dữ liệu</div>
                        <div className="sub">Nhập Group ID bên trái để bắt đầu cào</div>
                    </div>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden' }}>
                        <div style={{ flex: 1, overflowY: 'auto', overflowX: 'auto' }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '14px' }}>
                                <thead style={{ background: 'var(--bg-primary)', position: 'sticky', top: 0, zIndex: 10 }}>
                                    <tr>
                                        <th className="cb-cell" style={{ padding: '16px 8px', borderBottom: '1px solid var(--border)' }}>
                                            <input type="checkbox" checked={allSelected} onChange={e => toggleSelectAll(e.target.checked)} />
                                        </th>
                                        <th style={{ padding: '16px 24px', borderBottom: '1px solid var(--border)', minWidth: '150px', fontWeight: 500, color: 'var(--text-muted)', cursor: 'pointer' }} onClick={() => changeSort('author')}>
                                            Tác giả {sort === 'author' && (order === 'DESC' ? '▼' : '▲')}
                                        </th>
                                        <th style={{ padding: '16px 24px', borderBottom: '1px solid var(--border)', minWidth: '150px', fontWeight: 500, color: 'var(--text-muted)', cursor: 'pointer' }} onClick={() => changeSort('time')}>
                                            Giờ đăng {sort === 'time' && (order === 'DESC' ? '▼' : '▲')}
                                        </th>
                                        <th style={{ padding: '16px 16px', borderBottom: '1px solid var(--border)', minWidth: '130px', fontWeight: 500, color: 'var(--text-muted)', position: 'relative' }}>
                                            <div className="status-filter-btn" onClick={() => setStatusDropdownOpen(!statusDropdownOpen)}>
                                                <span>Trạng thái</span>
                                                <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor"><path d="M2 4l3 3 3-3z" /></svg>
                                            </div>
                                            {statusDropdownOpen && (
                                                <div className="filter-dropdown-menu" style={{ display: 'block' }}>
                                                    <div className={`filter-dropdown-item ${statusFilter === '' ? 'active' : ''}`} onClick={() => handleStatusFilterChange('')}>Tất cả</div>
                                                    <div className={`filter-dropdown-item ${statusFilter === 'active' ? 'active' : ''}`} onClick={() => handleStatusFilterChange('active')}>🟢 Active</div>
                                                    <div className={`filter-dropdown-item ${statusFilter === 'inactive' ? 'active' : ''}`} onClick={() => handleStatusFilterChange('inactive')}>🔴 Inactive</div>
                                                </div>
                                            )}
                                        </th>
                                        <th style={{ padding: '16px 24px', borderBottom: '1px solid var(--border)', minWidth: '150px', fontWeight: 500, color: 'var(--text-muted)', cursor: 'pointer' }} onClick={() => changeSort('updated')}>
                                            Cập nhật {sort === 'updated' && (order === 'DESC' ? '▼' : '▲')}
                                        </th>
                                        <th style={{ padding: '16px 24px', borderBottom: '1px solid var(--border)', minWidth: '300px', fontWeight: 500, color: 'var(--text-muted)', cursor: 'pointer' }} onClick={() => changeSort('content')}>
                                            Nội dung {sort === 'content' && (order === 'DESC' ? '▼' : '▲')}
                                        </th>
                                        <th style={{ padding: '16px 24px', borderBottom: '1px solid var(--border)', minWidth: '120px', fontWeight: 500, color: 'var(--text-muted)', cursor: 'pointer' }} onClick={() => changeSort('reaction')}>
                                            Tương tác {sort === 'reaction' && (order === 'DESC' ? '▼' : '▲')}
                                        </th>
                                        <th style={{ padding: '16px 24px', borderBottom: '1px solid var(--border)', minWidth: '300px', fontWeight: 500, color: 'var(--text-muted)', cursor: 'pointer' }} onClick={() => changeSort('comment')}>
                                            Bình luận {sort === 'comment' && (order === 'DESC' ? '▼' : '▲')}
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {data.map((post: any, i: number) => {
                                        const isChecked = selectedPosts.has(String(post.id || post.post_id));
                                        const postId = post.post_id || post.id;
                                        let cc = post.comment_count || 0;
                                        const crawled = post.crawled_comment_count || 0;
                                        if (crawled > cc) cc = crawled;

                                        return (
                                            <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                                                <td className="cb-cell" style={{ padding: '16px 8px', verticalAlign: 'top' }}>
                                                    <input type="checkbox" checked={isChecked} onChange={() => toggleSelection(String(postId))} />
                                                </td>
                                                <td style={{ padding: '16px 24px', verticalAlign: 'top' }}>
                                                    <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                                                        <div style={{ width: '32px', height: '32px', borderRadius: '50%', background: 'var(--bg-tertiary)', overflow: 'hidden', flexShrink: 0 }}>
                                                            {post.avatar_url && <img src={post.avatar_url} style={{ width: '100%', height: '100%', objectFit: 'cover' }} referrerPolicy="no-referrer" />}
                                                        </div>
                                                        <div style={{ display: 'flex', flexDirection: 'column' }}>
                                                            <b style={{ color: 'var(--accent)', fontSize: '14px' }}>{post.author_name || 'Ẩn danh'}</b>
                                                            {post.profile_url && <a href={post.profile_url} target="_blank" style={{ fontSize: '11px', color: 'var(--text-secondary)', textDecoration: 'none' }}>Xem trang cá nhân ↗</a>}
                                                        </div>
                                                    </div>
                                                </td>
                                                <td style={{ padding: '16px 24px', verticalAlign: 'top', color: 'var(--text-primary)', fontSize: '13px', fontWeight: 500 }}>
                                                    {post.creation_datetime ? new Date(post.creation_datetime).toLocaleString('vi-VN') : '—'}
                                                </td>
                                                <td style={{ padding: '16px 16px', verticalAlign: 'top' }}>
                                                    {post.is_active === false ? 
                                                        <span className="status-badge inactive">🔴 Inactive</span> : 
                                                        <span className="status-badge active">🟢 Active</span>
                                                    }
                                                </td>
                                                <td style={{ padding: '16px 24px', verticalAlign: 'top', color: 'var(--text-secondary)', fontSize: '13px' }}>
                                                    {post.updated_at ? new Date(post.updated_at).toLocaleString('vi-VN') : '—'}
                                                </td>
                                                <td style={{ padding: '16px 24px', verticalAlign: 'top' }}>
                                                    <div style={{ color: 'var(--text-primary)', lineHeight: 1.5, marginBottom: '8px' }}>
                                                        {post.message_text ? 
                                                            (post.message_text.length > 200 ? post.message_text.substring(0, 200) + '...' : post.message_text) 
                                                            : <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>Không có nội dung</span>
                                                        }
                                                    </div>
                                                    {post.permalink_url && <a href={post.permalink_url} target="_blank" style={{ fontSize: '12px', color: 'var(--accent)', textDecoration: 'none' }}>Xem bài viết gốc ↗</a>}
                                                </td>
                                                <td style={{ padding: '16px 24px', verticalAlign: 'top', fontWeight: 'bold', color: 'var(--text-primary)' }}>
                                                    👍 {post.reaction_count || 0}
                                                </td>
                                                <td style={{ padding: '16px 24px', verticalAlign: 'top' }}>
                                                    {(() => {
                                                        const isCrawlingThis = commentCrawlProgress[postId]?.status === 'running';
                                                        if (isCrawlingThis) {
                                                            return (
                                                                <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                                                                    <button 
                                                                        className="btn-comment crawling" 
                                                                        onClick={(e) => {
                                                                            e.stopPropagation();
                                                                            stopCommentCrawl(postId);
                                                                        }}
                                                                        style={{ 
                                                                            cursor: 'pointer',
                                                                            background: 'rgba(239, 68, 68, 0.15)',
                                                                            borderColor: 'rgba(239, 68, 68, 0.4)',
                                                                            color: '#ef4444',
                                                                            fontWeight: 600
                                                                        }}
                                                                        title="Nhấn vào đây để DỪNG lấy bình luận"
                                                                    >
                                                                        <span className="spinner-sm" style={{ marginRight: '6px', borderColor: '#ef4444', borderTopColor: 'transparent' }}></span>
                                                                        <span>🛑 Dừng ({commentCrawlProgress[postId]?.total || crawled || 0})</span>
                                                                    </button>
                                                                    <button
                                                                        onClick={() => openComments(post)}
                                                                        style={{
                                                                            background: 'var(--bg-tertiary)',
                                                                            border: '1px solid var(--border)',
                                                                            borderRadius: '4px',
                                                                            padding: '4px 8px',
                                                                            cursor: 'pointer',
                                                                            fontSize: '12px'
                                                                        }}
                                                                        title="Xem bình luận trong popup"
                                                                    >
                                                                        👁️
                                                                    </button>
                                                                </div>
                                                            );
                                                        }

                                                        if (crawled > 0) {
                                                            return (
                                                                <button 
                                                                    className="btn-comment has-data"
                                                                    onClick={() => openComments(post)}
                                                                    style={{ cursor: 'pointer' }}
                                                                    title="Nhấn để xem danh sách bình luận đã lưu"
                                                                >
                                                                    💬 {crawled} / {cc} đã lấy
                                                                </button>
                                                            );
                                                        }
                                                        if (cc > 0) {
                                                            const isCommentActionBlocked = crawling || feedCrawling;
                                                            return (
                                                                <>
                                                                    <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '6px' }}>{cc} bình luận</div>
                                                                    <button 
                                                                        className={`btn-comment ${isCommentActionBlocked ? 'disabled' : ''}`}
                                                                        disabled={isCommentActionBlocked} 
                                                                        style={isCommentActionBlocked ? { 
                                                                            opacity: 0.5, 
                                                                            cursor: 'not-allowed'
                                                                        } : { cursor: 'pointer' }} 
                                                                        title={isCommentActionBlocked ? "⚠️ Đang cào bài viết (Post), tạm thời không thể lấy bình luận" : "Nhấn để mở và lấy bình luận"}
                                                                        onClick={() => !isCommentActionBlocked && openComments(post)}
                                                                    >
                                                                        ⬇️ Lấy bình luận
                                                                    </button>
                                                                </>
                                                            );
                                                        }
                                                        return <span style={{ color: 'var(--text-muted)', fontSize: '12px' }}>0 bình luận</span>;
                                                    })()}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                        
                        {/* Pagination Controls */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 32px', borderTop: '1px solid var(--border)', background: 'var(--bg-primary)' }}>
                            <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
                                Tổng: <b style={{ color: 'var(--text-primary)' }}>{total}</b> bài viết
                            </div>
                            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                                <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1} style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '4px 12px', borderRadius: '6px', fontSize: '13px', cursor: 'pointer', opacity: page <= 1 ? 0.5 : 1 }}>&lt; Trước</button>
                                <span style={{ fontSize: '13px', color: 'var(--text-primary)' }}>Trang <b>{page}</b> / <b>{totalPages}</b></span>
                                <button onClick={() => setPage(Math.min(totalPages, page + 1))} disabled={page >= totalPages} style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '4px 12px', borderRadius: '6px', fontSize: '13px', cursor: 'pointer', opacity: page >= totalPages ? 0.5 : 1 }}>Sau &gt;</button>
                                <select value={limit} onChange={e => setLimit(Number(e.target.value))} style={{ background: 'var(--bg-tertiary)', border: '1px solid var(--border)', color: 'var(--text-primary)', padding: '4px 8px', borderRadius: '6px', fontSize: '13px', outline: 'none', marginLeft: '16px' }}>
                                    <option value="10">10 / trang</option>
                                    <option value="20">20 / trang</option>
                                    <option value="50">50 / trang</option>
                                </select>
                            </div>
                        </div>
                    </div>
                )}
                
                {/* Floating Action Bar */}
                <div className={`fab-bar ${selectedPosts.size > 0 ? 'visible' : ''}`}>
                    <span className="fab-count">✅ {selectedPosts.size} bài đã chọn</span>
                    <button 
                        className="fab-btn" 
                        disabled={feedCrawling}
                        style={feedCrawling ? { opacity: 0.6, cursor: 'not-allowed' } : {}}
                        onClick={bulkRefresh}
                        title={feedCrawling ? "Đang xử lý làm mới..." : "Làm mới lượt tương tác, bình luận và trạng thái các bài đã chọn"}
                    >
                        {feedCrawling ? '⏳ Đang làm mới...' : '🔄 Làm mới'}
                    </button>
                    <button className="fab-btn" onClick={bulkCheckStatus}>🔍 Kiểm tra</button>
                    <button 
                        className="fab-btn primary" 
                        disabled={crawling}
                        title={crawling ? "⚠️ Đang có tiến trình cào bài viết (Post) đang chạy. Không thể cào bình luận cùng lúc." : ""}
                        style={{ opacity: crawling ? 0.5 : 1, cursor: crawling ? 'not-allowed' : 'pointer' }}
                        onClick={bulkCrawlComments}
                    >
                        💬 Cào BL
                    </button>
                    <button className="fab-btn" onClick={bulkExportCsv}>📥 CSV</button>
                    <button className="fab-btn danger" onClick={bulkDelete}>🗑️ Xóa</button>
                </div>
            </div>

            {/* Comment Modal */}
            {modalOpen && selectedPost && (
                <div className="modal-overlay active" onClick={(e) => { 
                    const pid = selectedPost.post_id || selectedPost.id;
                    const isCrawling = commentCrawlProgress[pid]?.status === 'running';
                    if (e.target === e.currentTarget && !isCrawling) closeComments(); 
                }}>
                    <div className="modal-content" style={{ maxWidth: '640px', width: '90%' }}>
                        <div className="modal-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <div>
                                <h3 style={{ margin: 0, fontSize: '16px' }}>💬 Bình luận bài viết</h3>
                                <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                                    Tác giả: <b style={{ color: 'var(--accent)' }}>{selectedPost.author_name || 'Ẩn danh'}</b>
                                    {selectedPost.comment_count > 0 && ` • Tổng FB: ${selectedPost.comment_count}`}
                                    {comments.length > 0 && ` • Đã lưu: ${comments.length}`}
                                </div>
                            </div>
                            <button 
                                className="modal-close" 
                                onClick={closeComments} 
                            >
                                ✕
                            </button>
                        </div>
                        <div className="modal-body" style={{ maxHeight: '60vh', overflowY: 'auto' }}>
                            {(() => {
                                const pid = selectedPost.post_id || selectedPost.id;
                                const crawlInfo = commentCrawlProgress[pid];
                                const isCrawling = crawlInfo?.status === 'running' || crawlInfo?.status === 'queued';

                                if (comments.length === 0) {
                                    return (
                                        <div className="comment-empty">
                                            <div className="icon">💬</div>
                                            <p style={{ marginBottom: '16px' }}>Chưa có bình luận nào được tải về cho bài viết này.</p>
                                            {isCrawling ? (
                                                <button 
                                                    className="btn-crawl-sm danger" 
                                                    onClick={() => stopCommentCrawl(pid)}
                                                    style={{ 
                                                        padding: '8px 20px', 
                                                        fontSize: '13px', 
                                                        display: 'inline-flex', 
                                                        alignItems: 'center', 
                                                        gap: '8px', 
                                                        margin: '0 auto',
                                                        background: '#ef4444',
                                                        color: '#fff',
                                                        border: 'none',
                                                        cursor: 'pointer'
                                                    }}
                                                    title="Nhấn vào đây để DỪNG cào bình luận"
                                                >
                                                    <span className="spinner-sm" style={{ borderColor: '#fff', borderTopColor: 'transparent' }}></span>
                                                    <span>🛑 Dừng cào ({crawlInfo?.total || 0} đã lấy)</span>
                                                </button>
                                            ) : (
                                                <button 
                                                    className="btn-crawl-sm" 
                                                    disabled={crawling}
                                                    onClick={() => handleStartCrawlComments(selectedPost)}
                                                    title={crawling ? "⚠️ Đang có tiến trình cào bài viết (Post) đang chạy. Không thể cào bình luận cùng lúc." : ""}
                                                    style={{ 
                                                        padding: '8px 20px', 
                                                        fontSize: '13px', 
                                                        display: 'inline-flex', 
                                                        alignItems: 'center', 
                                                        gap: '8px', 
                                                        margin: '0 auto',
                                                        opacity: crawling ? 0.5 : 1,
                                                        cursor: crawling ? 'not-allowed' : 'pointer'
                                                    }}
                                                >
                                                    {crawling ? (
                                                        <>
                                                            <span>⚠️</span>
                                                            <span>Đang cào bài viết (Post)...</span>
                                                        </>
                                                    ) : (
                                                        <>
                                                            <span>⬇️</span>
                                                            <span>Bắt đầu cào bình luận ngay</span>
                                                        </>
                                                    )}
                                                </button>
                                            )}
                                        </div>
                                    );
                                }

                                return (
                                    <>
                                        {crawling && (
                                            <div style={{ padding: '8px 12px', marginBottom: '12px', background: 'rgba(234, 179, 8, 0.1)', border: '1px solid rgba(234, 179, 8, 0.3)', borderRadius: '6px', fontSize: '12px', color: '#eab308', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                <span>⚠️</span>
                                                <span>Đang có tiến trình cào bài viết (Post) đang chạy. Tính năng cào bình luận tạm thời bị khóa cho đến khi cào bài viết xong.</span>
                                            </div>
                                        )}
                                        {isCrawling && (
                                            <div style={{ padding: '8px 12px', marginBottom: '12px', background: 'rgba(59, 130, 246, 0.1)', border: '1px solid rgba(59, 130, 246, 0.2)', borderRadius: '6px', fontSize: '12px', color: 'var(--accent)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                <span className="spinner-sm"></span>
                                                <span>{crawlInfo?.message || 'Đang cập nhật thêm bình luận...'}</span>
                                            </div>
                                        )}
                                        {comments.map((c, idx) => (
                                            <div key={idx} className="comment-item">
                                                <div className="c-header">
                                                    <div className="c-avatar">
                                                        {(c.avatar_url || c.author_avatar) ? (
                                                            <img src={c.avatar_url || c.author_avatar} referrerPolicy="no-referrer" />
                                                        ) : (
                                                            <span style={{ fontSize: '14px' }}>👤</span>
                                                        )}
                                                    </div>
                                                    <div className="c-name">{c.author_name || 'Người dùng Facebook'}</div>
                                                    <div className="c-time">{c.creation_datetime ? new Date(c.creation_datetime).toLocaleString('vi-VN') : ''}</div>
                                                </div>
                                                <div className="c-body">
                                                    {c.body_text || c.message_text ? (
                                                        c.body_text || c.message_text
                                                    ) : (
                                                        <span style={{ color: 'var(--text-muted)', fontStyle: 'italic', fontSize: '12px' }}>[Hình ảnh / Nhãn dán / Không có nội dung chữ]</span>
                                                    )}
                                                </div>
                                            </div>
                                        ))}
                                    </>
                                );
                            })()}
                        </div>
                        <div className="modal-footer" style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                            {(() => {
                                const pid = selectedPost.post_id || selectedPost.id;
                                const crawlInfo = commentCrawlProgress[pid];
                                const isCrawling = crawlInfo?.status === 'running' || crawlInfo?.status === 'queued';

                                return (
                                    <>
                                        {comments.length > 0 && (
                                            isCrawling ? (
                                                <button 
                                                    className="btn-crawl-sm danger" 
                                                    onClick={() => stopCommentCrawl(pid)}
                                                    style={{ 
                                                        display: 'inline-flex', 
                                                        alignItems: 'center', 
                                                        gap: '6px',
                                                        background: '#ef4444',
                                                        color: '#fff',
                                                        border: 'none',
                                                        cursor: 'pointer'
                                                    }}
                                                    title="Nhấn vào đây để DỪNG cào bình luận"
                                                >
                                                    <span className="spinner-sm" style={{ borderColor: '#fff', borderTopColor: 'transparent' }}></span>
                                                    <span>🛑 Dừng cào ({crawlInfo?.total || comments.length})</span>
                                                </button>
                                            ) : (
                                                <button 
                                                    className="btn-crawl-sm" 
                                                    disabled={crawling}
                                                    onClick={() => handleStartCrawlComments(selectedPost)}
                                                    title={crawling ? "⚠️ Đang có tiến trình cào bài viết (Post) đang chạy. Không thể cào bình luận cùng lúc." : ""}
                                                    style={{ 
                                                        display: 'inline-flex', 
                                                        alignItems: 'center', 
                                                        gap: '6px',
                                                        opacity: crawling ? 0.5 : 1,
                                                        cursor: crawling ? 'not-allowed' : 'pointer'
                                                    }}
                                                >
                                                    {crawling ? '⚠️ Đang cào bài viết...' : '🔄 Cập nhật / Cào tiếp'}
                                                </button>
                                            )
                                        )}
                                        <button 
                                            style={{
                                                background: 'var(--bg-tertiary)',
                                                border: '1px solid var(--border)',
                                                color: 'var(--text-primary)',
                                                padding: '6px 14px',
                                                borderRadius: '6px',
                                                fontSize: '12px',
                                                cursor: 'pointer'
                                            }}
                                            onClick={closeComments}
                                        >
                                            Đóng
                                        </button>
                                    </>
                                );
                            })()}
                        </div>
                    </div>
                </div>
            )}

            {/* Toast Container */}
            <div id="toastContainer" className="toast-container">
                {toastMessage && (
                    <div className="toast show">
                        <div className="toast-icon">{toastMessage.icon}</div>
                        <div className="toast-content" dangerouslySetInnerHTML={{ __html: toastMessage.message }}></div>
                    </div>
                )}
            </div>
        </div>
    );
};
