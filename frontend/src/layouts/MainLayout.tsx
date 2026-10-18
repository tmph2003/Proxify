import React, { useEffect, useState } from 'react';
import { Outlet, NavLink } from 'react-router-dom';
import { useAppContext } from '../AppContext';

interface ExtensionNav {
    name: string;
    title: string;
    path: string;
    icon?: string;
    order?: number;
}

export const MainLayout: React.FC = () => {
    const { stats, connected } = useAppContext();
    const [extensions, setExtensions] = useState<ExtensionNav[]>([]);

    useEffect(() => {
        fetch('/api/extensions')
            .then(res => res.json())
            .then(data => {
                if (data && data.enabled && Array.isArray(data.extensions)) {
                    setExtensions(data.extensions);
                }
            })
            .catch(() => {});
    }, []);

    const renderExtensionIcon = (ext: ExtensionNav) => {
        if (ext.icon) {
            return <span>{ext.icon}</span>;
        }
        return <span>🧩</span>;
    };

    return (
        <>
            <div className="topbar">
                <div className="logo">
                    <img src="/assets/logo.png" alt="Logo" style={{ width: '20px', height: '20px', borderRadius: '4px' }} />
                    Proxify
                </div>
                <div className="nav-links">
                    <NavLink to="/" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
                        📡 Requests
                    </NavLink>
                    {extensions.map(ext => (
                        <NavLink
                            key={ext.name}
                            to={ext.path}
                            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                        >
                            {renderExtensionIcon(ext)}
                            {ext.title}
                        </NavLink>
                    ))}
                </div>
                <div className="conn-status">
                    <div className={`conn-dot ${connected ? 'connected' : ''}`}></div>
                    <span>{connected ? 'Connected' : 'Connecting...'}</span>
                </div>
                <div className="stats-bar">
                    <div className="stat">Requests: <span className="stat-value">{stats.requests}</span></div>
                    <div className="stat">Domains: <span className="stat-value">{stats.domains}</span></div>
                    <div className="stat">GraphQL: <span className="stat-value">{stats.graphql}</span></div>
                </div>
            </div>
            <Outlet />
        </>
    );
};

