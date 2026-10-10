import React, { createContext, useContext } from 'react';
import type { ReactNode } from 'react';
import { useRequests, type ProxyRequest } from './hooks/useRequests';

interface AppContextType {
    requests: ProxyRequest[];
    stats: { requests: number; domains: number; graphql: number };
    connected: boolean;
    clearRequests: () => void;
}

const AppContext = createContext<AppContextType | null>(null);

export const AppProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
    const value = useRequests();
    return (
        <AppContext.Provider value={value}>
            {children}
        </AppContext.Provider>
    );
};

export const useAppContext = () => {
    const context = useContext(AppContext);
    if (!context) {
        throw new Error('useAppContext must be used within an AppProvider');
    }
    return context;
};
