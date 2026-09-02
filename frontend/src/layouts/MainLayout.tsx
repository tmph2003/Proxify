import React from 'react';
import { Outlet, NavLink } from 'react-router-dom';
import { useAppContext } from '../AppContext';

export const MainLayout: React.FC = () => {
    const { stats, connected } = useAppContext();

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
                    <NavLink to="/zalo" className={({ isActive }) => `nav-link ${isActive ? 'active-zalo' : ''}`}>
                        <svg xmlns="http://www.w3.org/2000/svg" width="28" height="14" viewBox="0 0 40 20">
                            <rect width="40" height="20" rx="4" fill="#0068ff" />
                            <text x="50%" y="55%" dominantBaseline="middle" textAnchor="middle" fill="#fff" fontFamily="Arial, sans-serif" fontWeight="bold" fontSize="11">Zalo</text>
                        </svg>
                        Zalo Extractor
                    </NavLink>
                    <NavLink to="/facebook" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
                        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M22.675 0h-21.35c-.732 0-1.325.593-1.325 1.325v21.351c0 .731.593 1.324 1.325 1.324h11.495v-9.294h-3.128v-3.622h3.128v-2.671c0-3.1 1.893-4.788 4.659-4.788 1.325 0 2.463.099 2.795.143v3.24l-1.918.001c-1.504 0-1.795.715-1.795 1.763v2.313h3.587l-.467 3.622h-3.12v9.293h6.116c.73 0 1.323-.593 1.323-1.325v-21.35c0-.732-.593-1.325-1.325-1.325z" />
                        </svg>
                        Facebook Extractor
                    </NavLink>
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
