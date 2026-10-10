import { useState, useEffect, useCallback } from 'react';
import { getRequests, getStats } from '../api/client';

export interface ProxyRequest {
    id: number;
    req_uuid: string;
    method: string;
    url: string;
    domain: string;
    path: string;
    status_code: number;
    response_content_type: string;
    response_size: number;
    timestamp: string | number;
    is_graphql: boolean;
    graphql_operation?: string;
    request_body?: string;
    response_body?: string;
}

export const useRequests = () => {
    const [requests, setRequests] = useState<ProxyRequest[]>([]);
    const [stats, setStats] = useState({ requests: 0, domains: 0, graphql: 0 });
    const [connected, setConnected] = useState(false);

    // Initial load
    useEffect(() => {
        getRequests({ limit: 100 }).then(data => {
            if (Array.isArray(data)) {
                setRequests(data);
            }
        }).catch(console.error);

        getStats().then(data => {
            if (data) setStats(data);
        }).catch(console.error);
    }, []);

    // WebSocket connection
    useEffect(() => {
        let ws: WebSocket;
        let reconnectTimer: number | undefined;

        const connectWS = () => {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

            ws.onopen = () => {
                setConnected(true);
                if (reconnectTimer) clearTimeout(reconnectTimer);
            };

            ws.onmessage = (e) => {
                try {
                    const msg = JSON.parse(e.data);
                    if (msg.type === 'new_request') {
                        setRequests(prev => [msg.data, ...prev].slice(0, 500)); // Keep last 500
                        getStats().then(data => {
                            if (data) setStats(data);
                        });
                    } else if (msg.type === 'update_id') {
                        setRequests(prev => prev.map(r => 
                            r.req_uuid === msg.data.req_uuid ? { ...r, id: msg.data.row_id } : r
                        ));
                    }
                } catch (err) {
                    console.error('Error parsing WS message', err);
                }
            };

            ws.onclose = () => {
                setConnected(false);
                reconnectTimer = setTimeout(connectWS, 3000);
            };

            ws.onerror = () => {
                ws.close();
            };
        };

        connectWS();

        return () => {
            if (ws) {
                ws.onclose = null;
                ws.close();
            }
            if (reconnectTimer) clearTimeout(reconnectTimer);
        };
    }, []);

    const clearRequests = useCallback(() => {
        setRequests([]);
    }, []);

    return { requests, stats, connected, clearRequests };
};
