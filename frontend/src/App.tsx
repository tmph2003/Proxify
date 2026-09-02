import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { MainLayout } from './layouts/MainLayout';
import { ZaloPage } from './pages/Zalo';
import { FacebookPage } from './pages/Facebook';
import { DashboardPage } from './pages/Dashboard';
import { AppProvider } from './AppContext';

const App: React.FC = () => {
    return (
        <AppProvider>
            <BrowserRouter>
                <Routes>
                    <Route path="/" element={<MainLayout />}>
                        <Route index element={<DashboardPage />} />
                        <Route path="zalo" element={<ZaloPage />} />
                        <Route path="facebook" element={<FacebookPage />} />
                    </Route>
                </Routes>
            </BrowserRouter>
        </AppProvider>
    );
};

export default App;
