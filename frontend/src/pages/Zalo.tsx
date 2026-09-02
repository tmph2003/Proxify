import React, { useState } from 'react';
import { useZalo } from '../hooks/useZalo';

export const ZaloPage: React.FC = () => {
    const { 
        jobs, groups, selectedGroup, members,
        search, setSearch, toastMessage, selectGroup, cancelJob, fetchZaloUrl, fetchMembers 
    } = useZalo();
    const [url, setUrl] = useState('');
    const [memberSearch, setMemberSearch] = useState('');
    const [page, setPage] = useState(1);
    const pageSize = 100;

    const [sortField, setSortField] = useState<string>('');
    const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('asc');

    const filteredMembers = members.filter((m: any) => {
        if (!memberSearch) return true;
        const s = memberSearch.toLowerCase();
        return (m.display_name || '').toLowerCase().includes(s) ||
               (m.phone || '').toLowerCase().includes(s) ||
               (m.global_id || '').toLowerCase().includes(s);
    });

    const sortedMembers = [...filteredMembers].sort((a, b) => {
        if (!sortField) return 0;
        let valA = a[sortField] || '';
        let valB = b[sortField] || '';
        if (typeof valA === 'string') valA = valA.toLowerCase();
        if (typeof valB === 'string') valB = valB.toLowerCase();
        
        if (valA < valB) return sortOrder === 'asc' ? -1 : 1;
        if (valA > valB) return sortOrder === 'asc' ? 1 : -1;
        return 0;
    });

    React.useEffect(() => {
        setPage(1);
    }, [memberSearch, selectedGroup]);

    const totalPages = Math.max(1, Math.ceil(sortedMembers.length / pageSize));
    const paginatedMembers = sortedMembers.slice((page - 1) * pageSize, page * pageSize);

    const handleSort = (field: string) => {
        if (sortField === field) {
            setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
        } else {
            setSortField(field);
            setSortOrder('asc');
        }
    };

    const handleExport = (format: string) => {
        if (!selectedGroup) return;
        const params = new URLSearchParams({ group_id: selectedGroup.group_id });
        window.open(`/api/zalo/members/export/${format}?${params}`, '_blank');
    };

    return (
        <div className="main-container">
            {toastMessage && (
                <div style={{
                    position: 'fixed',
                    bottom: '20px',
                    right: '20px',
                    background: 'var(--green)',
                    color: 'white',
                    padding: '12px 24px',
                    borderRadius: '8px',
                    boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
                    zIndex: 9999,
                    animation: 'fadeInUp 0.3s ease-out'
                }}>
                    {toastMessage}
                </div>
            )}
            <div className="left-panel">
                <div className="scan-area">
                    <h3 style={{ margin: '0 0 8px' }}>QUÉT NHÓM</h3>
                    <div className="scan-input-group">
                        <input 
                            type="text" 
                            className="scan-input"
                            value={url} 
                            onChange={e => setUrl(e.target.value)} 
                            onKeyDown={e => e.key === 'Enter' && fetchZaloUrl(url)}
                            placeholder="Dán link nhóm Zalo hoặc Group ID..." 
                        />
                        <button className="scan-btn" onClick={() => fetchZaloUrl(url)}>
                            🔍 Quét
                        </button>
                    </div>
                    <div style={{ marginTop: '8px', fontSize: '11px', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                        💡 Mở <a href="https://chat.zalo.me" target="_blank" rel="noreferrer" style={{ color: 'var(--zalo-blue)', textDecoration: 'none' }}>chat.zalo.me</a> trên Chrome (đang proxy) để tự động thu thập dữ liệu
                    </div>
                </div>
                
                <div className="jobs-section">
                    {jobs.map((job: any) => (
                        <div className="job-item" key={job.id}>
                            <div className="job-info">
                                <div className="job-title">{job.link}</div>
                                <div className="job-meta">
                                    {job.status === 'pending' && 'Đang chờ...'}
                                    {job.status === 'running' && 'Đang lấy dữ liệu...'}
                                    {job.status === 'completed' && 'Hoàn thành'}
                                    {job.status === 'error' && 'Lỗi'}
                                </div>
                            </div>
                            <div className={`job-status ${job.status}`}></div>
                            {(job.status === 'pending' || job.status === 'running') && (
                                <button className="action-btn" style={{ marginLeft: '8px', padding: '4px 8px' }} onClick={() => cancelJob(job.id)}>Hủy</button>
                            )}
                        </div>
                    ))}
                </div>

                <div className="group-list-header">
                    <h3>Danh sách nhóm</h3>
                    <input 
                        type="text" 
                        className="group-search"
                        value={search} 
                        onChange={e => setSearch(e.target.value)} 
                        placeholder="Tìm nhóm..."
                    />
                </div>
                <div className="group-list">
                    {groups.map((g: any) => {
                        const avatarLetter = (g.display_name || g.group_id).charAt(0).toUpperCase();
                        return (
                            <div 
                                key={g.group_id} 
                                className={`group-item ${selectedGroup?.group_id === g.group_id ? 'active' : ''}`}
                                onClick={() => selectGroup(g.group_id)}
                            >
                                <div className="group-avatar">{avatarLetter}</div>
                                <div className="group-info">
                                    <div className="group-name">{g.display_name || g.group_id}</div>
                                    <div className="group-meta">{g.db_member_count || g.total_member} thành viên</div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            <div className="right-panel">
                {selectedGroup ? (
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                        <div className="group-detail-header">
                            <div className="group-detail-avatar">
                                {(selectedGroup.display_name || selectedGroup.group_id).charAt(0).toUpperCase()}
                            </div>
                            <div className="group-detail-info">
                                <h2>{selectedGroup.display_name || selectedGroup.group_id}</h2>
                                <div className="meta">
                                    <span>{members.length} thành viên</span>
                                    <span style={{ fontFamily: "'JetBrains Mono', monospace" }}>{selectedGroup.group_id}</span>
                                </div>
                            </div>
                            <div className="group-detail-actions">
                                <button className="action-btn primary" onClick={() => fetchMembers(selectedGroup.group_id)}>
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.92-10.26l5.08 5.08"/></svg>
                                    Lấy toàn bộ thành viên
                                </button>
                                <button className="action-btn" onClick={() => handleExport('csv')}>📥 CSV</button>
                                <button className="action-btn" onClick={() => handleExport('json')}>📄 JSON</button>
                            </div>
                        </div>

                        <div className="member-toolbar">
                            <input 
                                type="text" 
                                className="member-search"
                                value={memberSearch}
                                onChange={e => setMemberSearch(e.target.value)}
                                placeholder="Tìm thành viên (tên, SĐT, ID)..." 
                            />
                            <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                                <div style={{ display: 'flex', gap: '8px' }}>
                                    <button 
                                        className="action-btn" 
                                        disabled={page === 1} 
                                        onClick={() => setPage(p => Math.max(1, p - 1))}
                                        style={{ padding: '4px 8px', minWidth: 'auto' }}
                                    >◀</button>
                                    <span style={{ fontSize: '12px', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center' }}>
                                        Trang {page} / {totalPages}
                                    </span>
                                    <button 
                                        className="action-btn" 
                                        disabled={page === totalPages} 
                                        onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                                        style={{ padding: '4px 8px', minWidth: 'auto' }}
                                    >▶</button>
                                </div>
                                <span className="member-count-badge">{filteredMembers.length} kết quả</span>
                            </div>
                        </div>

                        <div className="member-table-wrap" style={{ flex: 1, overflowY: 'auto' }}>
                            <table className="member-table">
                                <thead>
                                    <tr>
                                        <th style={{ width: '40px' }}>#</th>
                                        <th onClick={() => handleSort('display_name')} style={{ cursor: 'pointer' }}>Tên {sortField === 'display_name' && (sortOrder === 'asc' ? '↑' : '↓')}</th>
                                        <th onClick={() => handleSort('global_id')} style={{ cursor: 'pointer' }}>Global ID {sortField === 'global_id' && (sortOrder === 'asc' ? '↑' : '↓')}</th>
                                        <th onClick={() => handleSort('phone')} style={{ cursor: 'pointer' }}>Số điện thoại {sortField === 'phone' && (sortOrder === 'asc' ? '↑' : '↓')}</th>
                                        <th onClick={() => handleSort('updated_at')} style={{ cursor: 'pointer' }}>Cập nhật {sortField === 'updated_at' && (sortOrder === 'asc' ? '↑' : '↓')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {paginatedMembers.map((m: any, i: number) => {
                                        const updateTime = m.updated_at ? new Date(m.updated_at).toLocaleString('vi-VN') : '-';
                                        let displayPhone = m.phone || '-';
                                        if (displayPhone.startsWith('+84')) {
                                            displayPhone = '0' + displayPhone.slice(3);
                                        } else if (displayPhone.startsWith('84') && displayPhone.length > 9) {
                                            displayPhone = '0' + displayPhone.slice(2);
                                        } else {
                                            displayPhone = displayPhone.replace(/^\+/, '');
                                        }
                                        return (
                                            <tr key={i}>
                                                <td style={{ color: 'var(--text-muted)', fontFamily: "'JetBrains Mono', monospace", fontSize: '10px' }}>
                                                    {(page - 1) * pageSize + i + 1}
                                                </td>
                                                <td>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                        <img 
                                                            src={m.avatar || `data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" fill="%23333"/><text x="12" y="16" fill="white" font-family="sans-serif" font-size="12" text-anchor="middle">${(m.display_name || '?').charAt(0).toUpperCase()}</text></svg>`}
                                                            style={{ width: '24px', height: '24px', borderRadius: '50%', objectFit: 'cover', background: '#333' }}
                                                            alt=""
                                                        />
                                                        <span>{m.display_name}</span>
                                                    </div>
                                                </td>
                                                <td style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: '11px', color: 'var(--text-muted)' }}>{m.global_id}</td>
                                                <td style={{ color: m.phone ? 'var(--green)' : 'inherit' }}>{displayPhone}</td>
                                                <td style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{updateTime}</td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    </div>
                ) : (
                    <div className="empty-state">
                        <div className="icon">💬</div>
                        <div className="text">Chọn một nhóm</div>
                        <div className="sub">Đang chờ tín hiệu...</div>
                    </div>
                )}
            </div>
        </div>
    );
};
