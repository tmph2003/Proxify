import { useState, useEffect, useCallback, useRef } from 'react';
import api from '../api/client';

export const useFacebook = () => {
    const [crawling, setCrawling] = useState(false);
    const [feedCrawling, setFeedCrawling] = useState(false);
    
    // Data states
    const [data, setData] = useState<any[]>([]);
    const [total, setTotal] = useState(0);
    const [groups, setGroups] = useState<any[]>([]);
    
    // UI states
    const [statusText, setStatusText] = useState('');
    const [statusColor, setStatusColor] = useState('var(--green)');
    const [cookie, setCookie] = useState(localStorage.getItem('fb_cookie') || '');
    const [toastMessage, setToastMessage] = useState<{ message: string, icon: string } | null>(null);
    const lastToastTimeRef = useRef<string | null>(null);
    
    // Pagination & Sorting & Filters
    const [page, setPage] = useState(1);
    const [limit, setLimit] = useState(20);
    const [sort, setSort] = useState('time');
    const [order, setOrder] = useState('DESC');
    
    // Filters
    const [groupIdFilter, setGroupIdFilter] = useState(sessionStorage.getItem('fb_filterGroupId') || '');
    const [groupNameFilter, setGroupNameFilter] = useState(sessionStorage.getItem('fb_filterGroupName') || '');
    const [statusFilter, setStatusFilter] = useState('');
    const [startDateFilter, setStartDateFilter] = useState(localStorage.getItem('fb_startDate') || '');
    const [endDateFilter, setEndDateFilter] = useState(localStorage.getItem('fb_endDate') || '');
    
    // Selections
    const [selectedPosts, setSelectedPosts] = useState<Set<string>>(new Set());

    const checkStatus = async () => {
        try {
            const { data: statObj } = await api.get('/facebook/crawl_status');
            const groupObj = statObj.group_crawl;

            if (groupObj && groupObj.message) {
                setStatusText(groupObj.message);
                if (groupObj.status === 'error') {
                    setStatusColor('var(--red)');
                } else if (groupObj.status === 'fetching_template') {
                    setStatusColor('var(--accent)');
                } else {
                    setStatusColor('var(--green)');
                }
            }

            if (groupObj && (groupObj.status === 'idle' || groupObj.status === 'error')) {
                setCrawling(false);
                if (groupObj.status === 'error') {
                    setStatusColor('var(--red)');
                } else {
                    setStatusColor('var(--green)');
                }
            }

            // Toast notification
            if (groupObj && groupObj.updated_at && groupObj.updated_at !== lastToastTimeRef.current) {
                lastToastTimeRef.current = groupObj.updated_at;
                if ((groupObj.last_p_count || 0) > 0 || (groupObj.last_c_count || 0) > 0) {
                    setToastMessage({
                        message: `Đã thu thập <b>${groupObj.last_p_count}</b> bài viết và <b>${groupObj.last_c_count}</b> bình luận mới.`,
                        icon: '🚀'
                    });
                    setTimeout(() => setToastMessage(null), 3000);
                }
            }
        } catch (e) {
            console.error(e);
        }
    };

    const fetchGroups = async () => {
        try {
            const { data: res } = await api.get('/facebook/groups');
            if (res.status === 'ok') {
                setGroups(res.data || []);
            }
        } catch (e) {
            console.error("Error fetching groups:", e);
        }
    };

    const fetchSyncedCookie = async () => {
        try {
            const { data: res } = await api.get('/facebook/cookie');
            if (res.status === 'ok' && res.cookie) {
                setCookie(res.cookie);
                localStorage.setItem('fb_cookie', res.cookie);
            }
        } catch (e) {
            console.error("Error fetching synced cookie:", e);
        }
    };

    const loadData = useCallback(async () => {
        try {
            const params: any = { sort, order, page, limit };
            if (groupIdFilter) params.group_id = groupIdFilter;
            if (groupNameFilter) params.group_name = groupNameFilter;
            if (statusFilter) params.status = statusFilter;
            if (startDateFilter) params.start_date = startDateFilter;
            if (endDateFilter) params.end_date = endDateFilter;

            const { data: res } = await api.get('/facebook/results', { params });
            if (res.status === 'ok') {
                setData(res.data || []);
                setTotal(res.total || 0);
            }
        } catch (e) {
            console.error(e);
        }
    }, [page, limit, sort, order, groupIdFilter, groupNameFilter, statusFilter, startDateFilter, endDateFilter]);

    const startCrawl = async (groupId: string, startDate: string, endDate: string) => {
        if (!cookie) {
            setStatusText('Vui lòng nhập cookie Facebook trước!');
            return;
        }
        if (!groupId) {
            setStatusText('Vui lòng nhập Group ID!');
            return;
        }
        try {
            setCrawling(true);
            setStatusText('Đang khởi tạo crawler...');
            await api.post('/facebook/crawl', { group_id: groupId, start_date: startDate, end_date: endDate });
            setStatusText('Đang thu thập dữ liệu...');
        } catch (e) {
            setCrawling(false);
            setStatusText('Lỗi khi khởi chạy crawler');
        }
    };

    const stopCrawl = async () => {
        try {
            await api.post('/facebook/stop_crawl');
            setCrawling(false);
            setStatusText('Đã dừng crawl.');
            setStatusColor('var(--accent)');
        } catch (e) {
            console.error(e);
        }
    };

    const saveCookie = async (newCookie: string, fbDtsg: string = '') => {
        setCookie(newCookie);
        localStorage.setItem('fb_cookie', newCookie);
        if (fbDtsg) {
            localStorage.setItem('fb_dtsg', fbDtsg);
        }
        try {
            await api.post('/facebook/cookie', { cookie: newCookie, fb_dtsg: fbDtsg });
        } catch (e) {
            console.error("Failed to save cookie to backend", e);
        }
    };

    const changeSort = (column: string) => {
        if (sort === column) {
            setOrder(order === 'DESC' ? 'ASC' : 'DESC');
        } else {
            setSort(column);
            setOrder('DESC');
        }
        setPage(1);
    };

    const selectGroup = (id: string, name: string) => {
        setGroupIdFilter(id);
        setGroupNameFilter(name);
        sessionStorage.setItem('fb_filterGroupId', id);
        sessionStorage.setItem('fb_filterGroupName', name);
        setPage(1);
    };

    const toggleSelection = (id: string) => {
        const newSet = new Set(selectedPosts);
        if (newSet.has(id)) newSet.delete(id);
        else newSet.add(id);
        setSelectedPosts(newSet);
    };

    const toggleSelectAll = (checked: boolean) => {
        if (checked) {
            setSelectedPosts(new Set(data.map(d => String(d.id))));
        } else {
            setSelectedPosts(new Set());
        }
    };

    // Bulk actions
    const bulkAction = async (endpoint: string, actionName: string) => {
        if (selectedPosts.size === 0) return;
        try {
            setFeedCrawling(true);
            await api.post(`/facebook/${endpoint}`, { ids: Array.from(selectedPosts) });
            alert(`Thành công: ${actionName}`);
            loadData();
        } catch (e) {
            alert(`Lỗi khi ${actionName}`);
        } finally {
            setFeedCrawling(false);
        }
    };

    const bulkRefresh = () => bulkAction('bulk_refresh', 'Làm mới');
    const bulkCheckStatus = () => bulkAction('bulk_check_status', 'Kiểm tra trạng thái');
    const bulkCrawlComments = () => bulkAction('bulk_crawl_comments', 'Cào bình luận');
    const bulkDelete = () => {
        if (window.confirm('Bạn có chắc muốn xóa các bài viết đã chọn?')) {
            bulkAction('bulk_delete', 'Xóa');
        }
    };
    
    const bulkExportCsv = async () => {
        if (selectedPosts.size === 0) return;
        try {
            const res = await api.post('/facebook/export_csv', { ids: Array.from(selectedPosts) });
            if (res.data.status === 'ok') {
                window.location.href = res.data.file_url;
            }
        } catch (e) {
            alert('Lỗi export CSV');
        }
    };

    const fetchComments = async (postId: string) => {
        try {
            const res = await api.get(`/facebook/comments?post_id=${postId}`);
            return res.data;
        } catch (e) {
            console.error(e);
            return null;
        }
    };

    useEffect(() => {
        checkStatus();
        fetchGroups();
        fetchSyncedCookie();
        
        const interval = setInterval(() => {
            checkStatus();
            fetchSyncedCookie();
        }, 3000);
        return () => clearInterval(interval);
    }, []);

    useEffect(() => {
        loadData();
    }, [loadData]);

    // Auto polling status
    useEffect(() => {
        let interval: ReturnType<typeof setInterval> | undefined;
        if (crawling) {
            interval = setInterval(() => {
                checkStatus();
            }, 1000);
        }
        return () => {
            if (interval) clearInterval(interval);
        };
    }, [crawling]);

    // Auto reload data every 5s while crawling
    useEffect(() => {
        const interval = setInterval(() => {
            if (crawling) {
                loadData();
            }
        }, 5000);
        return () => clearInterval(interval);
    }, [crawling, loadData]);

    return {
        crawling, data, statusText, statusColor, toastMessage, cookie, saveCookie,
        startCrawl, stopCrawl, loadData,
        page, setPage, limit, setLimit, total,
        sort, order, changeSort,
        groups, groupIdFilter, groupNameFilter, selectGroup,
        statusFilter, setStatusFilter,
        startDateFilter, setStartDateFilter, endDateFilter, setEndDateFilter,
        selectedPosts, toggleSelection, toggleSelectAll,
        bulkRefresh, bulkCheckStatus, bulkCrawlComments, bulkExportCsv, bulkDelete,
        feedCrawling, fetchComments, setCookie
    };
};
