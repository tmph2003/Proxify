import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { MainLayout } from './layouts/MainLayout';
import { DashboardPage } from './pages/Dashboard';
import { AppProvider } from './AppContext';

// Dynamically discover optional extension pages without hard imports
const extensionModules = import.meta.glob<{ [key: string]: any }>('./pages/*.tsx', { eager: true });

const dynamicRoutes = Object.entries(extensionModules)
    .map(([filePath, mod]) => {
        const match = filePath.match(/\.\/pages\/([^/]+)\.tsx$/);
        if (!match) return null;
        const pageName = match[1];
        if (pageName.toLowerCase() === 'dashboard') return null;
        const Component = mod[`${pageName}Page`] || mod.default;
        if (!Component) return null;
        return { path: pageName.toLowerCase(), Component };
    })
    .filter((item): item is { path: string; Component: React.ComponentType } => item !== null);

const App: React.FC = () => {
    return (
        <AppProvider>
            <BrowserRouter>
                <Routes>
                    <Route path="/" element={<MainLayout />}>
                        <Route index element={<DashboardPage />} />
                        {dynamicRoutes.map(({ path, Component }) => (
                            <Route key={path} path={path} element={<Component />} />
                        ))}
                        <Route path="*" element={<Navigate to="/" replace />} />
                    </Route>
                </Routes>
            </BrowserRouter>
        </AppProvider>
    );
};

export default App;

