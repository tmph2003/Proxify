import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { MainLayout } from './layouts/MainLayout';
import { DashboardPage } from './pages/Dashboard';
import { AppProvider } from './AppContext';

// Dynamically discover optional extension pages without hard imports
const extensionModules = import.meta.glob<{ [key: string]: any }>('./pages/*.tsx', { eager: true });

const zaloModule = extensionModules['./pages/Zalo.tsx'];
const facebookModule = extensionModules['./pages/Facebook.tsx'];

const ZaloComponent = zaloModule ? (zaloModule.ZaloPage || zaloModule.default) : null;
const FacebookComponent = facebookModule ? (facebookModule.FacebookPage || facebookModule.default) : null;

const App: React.FC = () => {
    return (
        <AppProvider>
            <BrowserRouter>
                <Routes>
                    <Route path="/" element={<MainLayout />}>
                        <Route index element={<DashboardPage />} />
                        {ZaloComponent && <Route path="zalo" element={<ZaloComponent />} />}
                        {FacebookComponent && <Route path="facebook" element={<FacebookComponent />} />}
                        <Route path="*" element={<Navigate to="/" replace />} />
                    </Route>
                </Routes>
            </BrowserRouter>
        </AppProvider>
    );
};

export default App;

