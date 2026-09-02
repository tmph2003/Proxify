import React, { useState } from 'react';
import { useAppContext } from '../AppContext';
import { getRequestDetails, getConfig, toggleDb, getDomains, exportRequests } from '../api/client';

export const DashboardPage: React.FC = () => {
    const { requests, clearRequests } = useAppContext();
    const [selectedId, setSelectedId] = useState<number | null>(null);
    const [selectedData, setSelectedData] = useState<any>(null);
    const [activeTab, setActiveTab] = useState<'overview' | 'request' | 'response' | 'graphql'>('overview');
    const [search, setSearch] = useState(() => sessionStorage.getItem('search') || '');
    const [methodFilter, setMethodFilter] = useState(() => sessionStorage.getItem('methodFilter') || '');
    const [statusFilter, setStatusFilter] = useState(() => sessionStorage.getItem('statusFilter') || '');
    const [domainFilter, setDomainFilter] = useState(() => sessionStorage.getItem('domainFilter') || '');
    const [gqlFilter, setGqlFilter] = useState(() => sessionStorage.getItem('gqlFilter') === 'true');
    const [autoScroll, setAutoScroll] = useState(() => sessionStorage.getItem('autoScroll') !== 'false');
    const [dbIntegrationEnabled, setDbIntegrationEnabled] = useState(() => sessionStorage.getItem('dbIntegrationEnabled') === 'true');
    const [domains, setDomains] = useState<any[]>([]);
    const [showDbDomainDropdown, setShowDbDomainDropdown] = useState(false);
    const [dbAllowedDomains, setDbAllowedDomains] = useState<string[]>([]);

    React.useEffect(() => {
        getDomains().then(data => {
            if (Array.isArray(data)) setDomains(data);
        }).catch(console.error);
    }, []);

    React.useEffect(() => {
        sessionStorage.setItem('search', search);
        sessionStorage.setItem('methodFilter', methodFilter);
        sessionStorage.setItem('statusFilter', statusFilter);
        sessionStorage.setItem('domainFilter', domainFilter);
        sessionStorage.setItem('gqlFilter', String(gqlFilter));
        sessionStorage.setItem('autoScroll', String(autoScroll));
        sessionStorage.setItem('dbIntegrationEnabled', String(dbIntegrationEnabled));
    }, [search, methodFilter, statusFilter, domainFilter, gqlFilter, autoScroll, dbIntegrationEnabled]);

    React.useEffect(() => {
        // We still fetch from backend to sync the actual DB toggle state
        getConfig().then(data => {
            if (data) {
                if (data.db_integration_enabled !== undefined) setDbIntegrationEnabled(data.db_integration_enabled);
                if (data.db_allowed_domains) setDbAllowedDomains(data.db_allowed_domains);
            }
        }).catch(console.error);
    }, []);

    const saveDbDomains = async () => {
        try {
            await toggleDb(dbIntegrationEnabled, dbAllowedDomains);
            setShowDbDomainDropdown(false);
        } catch (e) {
            console.error('Failed to save DB domains', e);
        }
    };

    const handleToggleDb = async () => {
        const newState = !dbIntegrationEnabled;
        setDbIntegrationEnabled(newState);
        try {
            await toggleDb(newState, dbAllowedDomains);
        } catch (e) {
            console.error('Failed to toggle DB integration', e);
            setDbIntegrationEnabled(!newState); // revert on failure
        }
    };

    const handleSelect = async (id: number) => {
        setSelectedId(id);
        if (id === 0) {
            setSelectedData(null);
            return;
        }
        try {
            const data = await getRequestDetails(id);
            setSelectedData(data);
            setActiveTab('overview');
        } catch (e) {
            console.error('Failed to load request details', e);
        }
    };

    const filteredRequests = requests.filter(r => {
        if (search) {
            const s = search.toLowerCase();
            const inUrl = (r.url || '').toLowerCase().includes(s);
            const inDomain = (r.domain || '').toLowerCase().includes(s);
            const inGql = (r.graphql_operation || '').toLowerCase().includes(s);
            if (!inUrl && !inDomain && !inGql) return false;
        }
        if (methodFilter && r.method !== methodFilter) return false;
        if (statusFilter && r.status_code?.toString() !== statusFilter) return false;
        if (domainFilter && r.domain !== domainFilter) return false;
        if (gqlFilter && !r.is_graphql) return false;
        return true;
    });

    const handleExport = (format: string) => {
        if (!selectedId || selectedId === 0) {
            alert('Vui lòng chọn 1 request hợp lệ để xuất dữ liệu.');
            return;
        }
        exportRequests(format, [selectedId]);
    };

    const listBodyRef = React.useRef<HTMLDivElement>(null);

    React.useEffect(() => {
        if (autoScroll && listBodyRef.current) {
            listBodyRef.current.scrollTop = 0;
        }
    }, [filteredRequests, autoScroll]);

    return (
        <>
            <div className="filter-bar">
                <div className="filter-group">
                    <input 
                        autoComplete="off" 
                        id="searchInput" 
                        placeholder="Tìm kiếm URL, body, GraphQL..." 
                        type="search"
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                    />
                    <select id="methodFilter" value={methodFilter} onChange={e => setMethodFilter(e.target.value)}>
                        <option value="">Tất cả Methods</option>
                        <option value="GET">GET</option>
                        <option value="POST">POST</option>
                        <option value="PUT">PUT</option>
                        <option value="DELETE">DELETE</option>
                        <option value="PATCH">PATCH</option>
                        <option value="OPTIONS">OPTIONS</option>
                    </select>
                    <select id="statusFilter" value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
                        <option value="">Tất cả Status</option>
                        <option value="200">200 OK</option>
                        <option value="301">301</option>
                        <option value="302">302</option>
                        <option value="400">400</option>
                        <option value="401">401</option>
                        <option value="403">403</option>
                        <option value="404">404</option>
                        <option value="500">500</option>
                    </select>
                    <select id="domainFilter" value={domainFilter} onChange={e => setDomainFilter(e.target.value)}>
                        <option value="">Tất cả Domains</option>
                        {domains.map((d: any) => (
                            <option key={d.domain} value={d.domain}>{d.domain} ({d.count})</option>
                        ))}
                    </select>
                    <div style={{ position: 'relative', display: 'inline-block' }}>
                        <button 
                            className={`filter-btn ${dbAllowedDomains.length > 0 ? 'active' : ''}`} 
                            id="dbDomainBtn"
                            onClick={() => setShowDbDomainDropdown(!showDbDomainDropdown)}
                        >
                            🎯 Lọc Ghi DB {dbAllowedDomains.length > 0 ? `(${dbAllowedDomains.length})` : '(Tất cả)'}
                        </button>
                        {showDbDomainDropdown && (
                            <div id="dbDomainDropdown" style={{ display: 'block', position: 'absolute', background: 'var(--bg-tertiary)', border: '1px solid var(--border)', borderRadius: '6px', padding: '8px', zIndex: 100, minWidth: '250px', maxHeight: '350px', overflowY: 'auto', boxShadow: '0 4px 12px rgba(0,0,0,0.2)', top: '100%', left: 0, marginTop: '4px' }}>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                    {domains.map((d: any) => (
                                        <label key={d.domain} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: 'var(--text-secondary)' }}>
                                            <input 
                                                type="checkbox" 
                                                value={d.domain} 
                                                checked={dbAllowedDomains.includes(d.domain)}
                                                onChange={e => {
                                                    if (e.target.checked) setDbAllowedDomains([...dbAllowedDomains, d.domain]);
                                                    else setDbAllowedDomains(dbAllowedDomains.filter(x => x !== d.domain));
                                                }}
                                            />
                                            {d.domain} <span style={{ opacity: 0.5 }}>({d.count})</span>
                                        </label>
                                    ))}
                                    {domains.length === 0 && <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>Chưa có domain nào</div>}
                                    <button onClick={saveDbDomains} style={{ marginTop: '8px', width: '100%', padding: '6px', background: 'var(--accent)', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}>Lưu thiết lập</button>
                                </div>
                            </div>
                        )}
                    </div>
                    <button 
                        className={`filter-btn ${dbIntegrationEnabled ? 'active' : ''}`} 
                        id="dbToggleBtn"
                        onClick={handleToggleDb}
                        style={dbIntegrationEnabled ? { borderColor: 'var(--green)', color: 'var(--green)', background: 'rgba(34, 197, 94, 0.1)' } : {}}
                    >
                        {dbIntegrationEnabled ? '🟢 Ghi DB: BẬT' : '🔴 Ghi DB: TẮT'}
                    </button>
                    <button 
                        className={`filter-btn ${gqlFilter ? 'active' : ''}`} 
                        id="gqlFilter"
                        onClick={() => setGqlFilter(!gqlFilter)}
                    >
                        GraphQL
                    </button>
                    <button 
                        className={`filter-btn ${autoScroll ? 'active' : ''}`} 
                        id="autoScrollBtn"
                        onClick={() => setAutoScroll(!autoScroll)}
                    >
                        ⬇ Auto-scroll
                    </button>
                </div>

                <div className="filter-group">
                    <div className="export-group" style={{ opacity: (!selectedId || selectedId === 0) ? 0.3 : 1, pointerEvents: (!selectedId || selectedId === 0) ? 'none' : 'auto' }}>
                        <button className="export-btn" onClick={() => handleExport('json')}>📄 JSON</button>
                        <button className="export-btn" onClick={() => handleExport('har')}>🌐 HAR</button>
                        <button className="export-btn" onClick={() => handleExport('python')}>🐍 Python</button>
                        <button className="export-btn" onClick={() => handleExport('curl')}>⚡ cURL</button>
                    </div>
                    <button className="filter-btn" style={{ color: 'var(--red)' }} onClick={clearRequests}>🗑 Clear</button>
                </div>
            </div>
            
            <div className="main">
                {/* Request List */}
                <div className="request-list">
                    <div className="list-header">
                        <span>#</span>
                        <span>Method</span>
                        <span>URL</span>
                        <span>Content-Type</span>
                        <span>Size</span>
                        <span>Status</span>
                        <span>Time</span>
                    </div>
                    <div className="list-body" ref={listBodyRef}>
                        {filteredRequests.map(req => (
                            <div 
                                key={req.req_uuid || req.id} 
                                className={`request-row ${selectedId === req.id ? 'active' : ''}`}
                                onClick={() => handleSelect(req.id)}
                            >
                                <span className="col-id">
                                    {req.id === 0 ? (
                                        <span style={{ color: 'var(--accent)', fontSize: '10px', letterSpacing: '1px', animation: 'pulse 1.5s infinite' }}>LIVE</span>
                                    ) : (
                                        req.id || ''
                                    )}
                                </span>
                                <span className={`col-method method-${req.method}`}>{req.method}</span>
                                <span className="col-url">
                                    {req.is_graphql ? <span className="gql-tag">GQL</span> : null}
                                    <span className="domain">{req.domain}</span>{req.path || ''}
                                </span>
                                <span className="col-type">{req.response_content_type || '-'}</span>
                                <span className="col-size">{req.response_size || 0} B</span>
                                <span className={`col-status status-${Math.floor(req.status_code/100)}xx`}>{req.status_code}</span>
                                <span className="col-time">{new Date(req.timestamp).toLocaleTimeString()}</span>
                            </div>
                        ))}
                    </div>
                </div>

                <div className="resize-handle"></div>

                {/* Detail Panel */}
                <div className="detail-panel">
                    {!selectedData ? (
                        <div className="detail-empty">
                            {selectedId === 0 ? (
                                <>
                                    <div className="icon">⚡</div>
                                    <div className="text">Request LIVE</div>
                                    <div className="subtext">Đang chờ lưu vào Database...</div>
                                </>
                            ) : (
                                <>
                                    <div className="icon">📡</div>
                                    <div className="text">Chọn một request để xem chi tiết</div>
                                </>
                            )}
                        </div>
                    ) : (
                        <div>
                            <div className="detail-tabs">
                                <div className={`detail-tab ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>Overview</div>
                                <div className={`detail-tab ${activeTab === 'request' ? 'active' : ''}`} onClick={() => setActiveTab('request')}>Request</div>
                                <div className={`detail-tab ${activeTab === 'response' ? 'active' : ''}`} onClick={() => setActiveTab('response')}>Response</div>
                                {!!selectedData.is_graphql && (
                                    <div className={`detail-tab ${activeTab === 'graphql' ? 'active' : ''}`} onClick={() => setActiveTab('graphql')}>GraphQL</div>
                                )}
                            </div>
                            <div className="detail-content">
                                {activeTab === 'overview' && (
                                    <div className="detail-section">
                                        <h3>URL</h3>
                                        <div className="detail-url">{selectedData.url}</div>
                                    </div>
                                )}
                                {activeTab === 'request' && (
                                    <div className="detail-section">
                                        <h3>Headers</h3>
                                        <pre className="body-content">{JSON.stringify(selectedData.request_headers, null, 2)}</pre>
                                        <h3>Body</h3>
                                        <pre className="body-content">{selectedData.request_body}</pre>
                                    </div>
                                )}
                                {activeTab === 'response' && (
                                    <div className="detail-section">
                                        <h3>Headers</h3>
                                        <pre className="body-content">{JSON.stringify(selectedData.response_headers, null, 2)}</pre>
                                        <h3>Body</h3>
                                        <pre className="body-content">{selectedData.response_body}</pre>
                                    </div>
                                )}
                                {activeTab === 'graphql' && selectedData.is_graphql && (
                                    <div className="detail-section">
                                        <h3>Operation</h3>
                                        <div className="gql-info">{selectedData.graphql_operation}</div>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </>
    );
};
