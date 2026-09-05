import { useState, useEffect, useCallback, useRef } from 'react';
import api from '../api/client';

export const useFacebook = () => {
    const [crawling, setCrawling] = useState(() => sessionStorage.getItem('fb_is_crawling') === 'true');
    const [feedCrawling, setFeedCrawling] = useState(() => sessionStorage.getItem('fb_is_feed_crawling') === 'true');
    
    // Data states
    const [data, setData] = useState<any[]>([]);
    const [total, setTotal] = useState(0);
    const [groups, setGroups] = useState<any[]>([]);
    
    // UI states
    const [statusText, setStatusText] = useState(() => sessionStorage.getItem('fb_statusText') || '');
    const [statusColor, setStatusColor] = useState(() => sessionStorage.getItem('fb_statusColor') || 'var(--green)');
    const [cookie, setCookie] = useState(localStorage.getItem('fb_cookie') || '');
    const [toastMessage, setToastMessage] = useState<{ message: string, icon: string } | null>(null);
    const lastToastTimeRef = useRef<string | null>(null);
    
    // Pagination & Sorting & Filters (Lưu theo Session)
    const [page, setPageState] = useState(() => Number(sessionStorage.getItem('fb_page')) || 1);
    const [limit, setLimitState] = useState(() => Number(sessionStorage.getItem('fb_limit')) || 20);
    const [sort, setSortState] = useState(() => sessionStorage.getItem('fb_sort') || 'time');
    const [order, setOrderState] = useState(() => sessionStorage.getItem('fb_order') || 'DESC');
    
    const setPage = (p: number) => {
        setPageState(p);
        sessionStorage.setItem('fb_page', String(p));
    };

    const setLimit = (l: number) => {
        setLimitState(l);
        sessionStorage.setItem('fb_limit', String(l));
        sessionStorage.setItem('fb_page', '1');
        setPageState(1);
    };

    // Filters (Lưu theo Session & LocalStorage)
    const [groupIdFilter, setGroupIdFilter] = useState(sessionStorage.getItem('fb_filterGroupId') || '');
    const [groupNameFilter, setGroupNameFilter] = useState(sessionStorage.getItem('fb_filterGroupName') || '');
    const [statusFilter, setStatusFilterState] = useState(() => sessionStorage.getItem('fb_statusFilter') || '');
    const [startDateFilter, setStartDateFilter] = useState(localStorage.getItem('fb_startDate') || '');
    const [endDateFilter, setEndDateFilter] = useState(localStorage.getItem('fb_endDate') || '');
    
    const setStatusFilter = (st: string) => {
        setStatusFilterState(st);
        sessionStorage.setItem('fb_statusFilter', st);
        sessionStorage.setItem('fb_page', '1');
        setPageState(1);
    };

    // Selections (Lưu theo Session)
    const [selectedPosts, setSelectedPosts] = useState<Set<string>>(() => {
        try {
            const raw = sessionStorage.getItem('fb_selected_posts');
            return raw ? new Set(JSON.parse(raw)) : new Set();
        } catch (e) {
            return new Set();
        }
    });

    const [commentCrawlProgress, setCommentCrawlProgress] = useState<{ [postId: string]: { status: string; message: string; total?: number } }>(() => {
        try {
            return JSON.parse(sessionStorage.getItem('fb_comment_progress') || '{}');
        } catch (e) {
            return {};
        }
    });

    const [backendIsCommentCrawling, setBackendIsCommentCrawling] = useState(false);

    const checkStatus = async () => {
        try {
            const { data: statObj } = await api.get('/facebook/crawl_status');
            const groupObj = statObj.group_crawl;

            if (typeof statObj.is_comment_crawling === 'boolean') {
                setBackendIsCommentCrawling(statObj.is_comment_crawling);
            }

            if (groupObj) {
                // Tự động khôi phục state cào nếu backend đang chạy
                if (groupObj.status === 'running' || groupObj.status === 'fetching_template') {
                    setCrawling(true);
                    sessionStorage.setItem('fb_is_crawling', 'true');
                } else if (groupObj.status === 'idle' || groupObj.status === 'error' || groupObj.status === 'blocked') {
                    setCrawling(false);
                    sessionStorage.removeItem('fb_is_crawling');
                }

                if (groupObj.message) {
                    setStatusText(groupObj.message);
                    sessionStorage.setItem('fb_statusText', groupObj.message);

                    let color = 'var(--green)';
                    if (groupObj.status === 'error' || groupObj.status === 'blocked') {
                        color = 'var(--red)';
                    } else if (groupObj.status === 'fetching_template' || groupObj.status === 'paused') {
                        color = 'var(--accent)';
                    }
                    setStatusColor(color);
                    sessionStorage.setItem('fb_statusColor', color);
                }
            }

            // Đồng bộ trạng thái cào hàng loạt / refresh
            if (statObj.refresh) {
                if (statObj.refresh.status === 'running') {
                    setFeedCrawling(true);
                    sessionStorage.setItem('fb_is_feed_crawling', 'true');
                } else if (statObj.refresh.status === 'idle' || statObj.refresh.status === 'done' || statObj.refresh.status === 'error') {
                    setFeedCrawling(false);
                    sessionStorage.removeItem('fb_is_feed_crawling');
                }
            }

            // Đồng bộ trạng thái cào bình luận từng bài viết
            if (statObj.comment_crawls && typeof statObj.comment_crawls === 'object') {
                setCommentCrawlProgress(prev => {
                    const merged = { ...prev, ...statObj.comment_crawls };
                    sessionStorage.setItem('fb_comment_progress', JSON.stringify(merged));
                    return merged;
                });
            }

            // Toast notification
            if (groupObj && groupObj.updated_at && groupObj.updated_at !== lastToastTimeRef.current) {
                lastToastTimeRef.current = groupObj.updated_at;
                if (groupObj.toast_message) {
                    setToastMessage({
                        message: groupObj.toast_message,
                        icon: groupObj.toast_icon || '⚠️'
                    });
                    setTimeout(() => setToastMessage(null), 5000);
                } else if ((groupObj.last_p_count || 0) > 0 || (groupObj.last_c_count || 0) > 0) {
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

    const startCrawl = async (groupId: string, startDate: string, endDate: string, targetType: string = 'group') => {
        if (isCommentCrawling) {
            alert('⚠️ Đang có tiến trình cào bình luận (Comment) đang chạy. Không thể cào bài viết cùng lúc. Vui lòng chờ hoàn tất.');
            return;
        }
        const activeCookie = cookie || localStorage.getItem('fb_cookie') || '';
        if (!activeCookie) {
            setStatusText('Vui lòng nhập cookie Facebook trước!');
            return;
        }
        if (!groupId) {
            const label = targetType === 'profile' ? 'Profile ID / URL' : 'Group ID';
            setStatusText(`Vui lòng nhập ${label}!`);
            return;
        }
        try {
            setCrawling(true);
            sessionStorage.setItem('fb_is_crawling', 'true');
            const initMsg = targetType === 'profile' 
                ? 'Đang khởi tạo crawler trang cá nhân...' 
                : 'Đang khởi tạo crawler...';
            setStatusText(initMsg);
            sessionStorage.setItem('fb_statusText', initMsg);
            await api.post('/facebook/crawl', {
                target_type: targetType,
                target_id: groupId,
                group_id: groupId,  // backward compat
                start_date: startDate,
                end_date: endDate,
                cookie: activeCookie
            });
            setStatusText('Đang thu thập dữ liệu...');
            sessionStorage.setItem('fb_statusText', 'Đang thu thập dữ liệu...');
        } catch (e) {
            setCrawling(false);
            sessionStorage.removeItem('fb_is_crawling');
            setStatusText('Lỗi khi khởi chạy crawler');
            sessionStorage.setItem('fb_statusText', 'Lỗi khi khởi chạy crawler');
        }
    };

    const stopCrawl = async () => {
        try {
            await api.post('/facebook/stop_crawl');
            setCrawling(false);
            sessionStorage.removeItem('fb_is_crawling');
            setStatusText('Đã dừng crawl.');
            sessionStorage.setItem('fb_statusText', 'Đã dừng crawl.');
            setStatusColor('var(--accent)');
            sessionStorage.setItem('fb_statusColor', 'var(--accent)');
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
        const newOrder = (sort === column && order === 'DESC') ? 'ASC' : 'DESC';
        setSortState(column);
        setOrderState(newOrder);
        sessionStorage.setItem('fb_sort', column);
        sessionStorage.setItem('fb_order', newOrder);
        sessionStorage.setItem('fb_page', '1');
        setPageState(1);
    };

    const selectGroup = (id: string, name: string) => {
        setGroupIdFilter(id);
        setGroupNameFilter(name);
        sessionStorage.setItem('fb_filterGroupId', id);
        sessionStorage.setItem('fb_filterGroupName', name);
        sessionStorage.setItem('fb_page', '1');
        setPageState(1);
    };

    const toggleSelection = (id: string) => {
        setSelectedPosts(prev => {
            const newSet = new Set(prev);
            if (newSet.has(id)) newSet.delete(id);
            else newSet.add(id);
            sessionStorage.setItem('fb_selected_posts', JSON.stringify(Array.from(newSet)));
            return newSet;
        });
    };

    const toggleSelectAll = (checked: boolean) => {
        const newSet = checked ? new Set(data.map(d => String(d.id || d.post_id))) : new Set<string>();
        setSelectedPosts(newSet);
        sessionStorage.setItem('fb_selected_posts', JSON.stringify(Array.from(newSet)));
    };

    // Bulk actions
    const bulkAction = async (action: string, actionName: string) => {
        if (selectedPosts.size === 0) {
            alert('Vui lòng chọn ít nhất 1 bài viết');
            return;
        }
        if (action === 'crawl_comments' && crawling) {
            alert('⚠️ Đang có tiến trình cào bài viết (Post) đang chạy. Không thể cào bình luận cùng lúc. Vui lòng chờ hoàn tất.');
            return;
        }
        try {
            setFeedCrawling(true);
            const activeCookie = cookie || localStorage.getItem('fb_cookie') || '';
            const res = await api.post('/facebook/bulk_action', {
                action,
                post_ids: Array.from(selectedPosts),
                cookie: activeCookie
            });

            if (res.data.status !== 'ok') {
                alert(`Lỗi: ${res.data.message || 'Không thể thực hiện tác vụ'}`);
                setFeedCrawling(false);
                return;
            }

            const taskId = res.data.task_id;
            if (taskId) {
                setToastMessage({ icon: '⏳', message: `Bắt đầu ${actionName.toLowerCase()}...` });
                const pollInterval = setInterval(async () => {
                    try {
                        const sRes = await api.get(`/facebook/bulk_status?task_id=${encodeURIComponent(taskId)}`);
                        const p = sRes.data?.progress;
                        if (p) {
                            setToastMessage({
                                icon: p.status === 'done' ? '✅' : (p.status === 'error' ? '❌' : '⏳'),
                                message: p.message || `${actionName}: đang xử lý...`
                            });

                            if (p.status === 'done' || p.status === 'error') {
                                clearInterval(pollInterval);
                                setFeedCrawling(false);
                                loadData();
                                setSelectedPosts(new Set());
                            }
                        }
                    } catch (err) {
                        // ignore poll errors
                    }
                }, 1500);
            } else {
                setToastMessage({ icon: '✅', message: `Hoàn tất: ${actionName}` });
                loadData();
                setSelectedPosts(new Set());
                setFeedCrawling(false);
            }
        } catch (e: any) {
            alert(`Lỗi khi ${actionName}: ${e.message || e}`);
            setFeedCrawling(false);
        }
    };

    const bulkRefresh = () => bulkAction('refresh', 'Làm mới');
    const bulkCheckStatus = () => bulkAction('check_status', 'Kiểm tra trạng thái');
    const bulkCrawlComments = () => bulkAction('crawl_comments', 'Cào bình luận');
    const bulkDelete = () => {
        if (window.confirm(`Bạn có chắc muốn xóa ${selectedPosts.size} bài viết đã chọn?`)) {
            bulkAction('delete', 'Xóa');
        }
    };
    
    const bulkExportCsv = async () => {
        if (selectedPosts.size === 0) return;
        try {
            const res = await api.post('/facebook/bulk_action', {
                action: 'export_csv',
                post_ids: Array.from(selectedPosts)
            }, { responseType: 'blob' });
            const blob = new Blob([res.data], { type: 'text/csv;charset=utf-8;' });
            const url = window.URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.setAttribute('download', `facebook_posts_${selectedPosts.size}.csv`);
            document.body.appendChild(link);
            link.click();
            link.remove();
            window.URL.revokeObjectURL(url);
        } catch (e) {
            alert('Lỗi export CSV');
        }
    };

    const crawlPostComments = async (postId: string, feedbackId?: string) => {
        if (crawling) {
            alert('⚠️ Đang có tiến trình cào bài viết (Post) đang chạy. Không thể cào bình luận cùng lúc. Vui lòng chờ hoàn tất.');
            return null;
        }
        try {
            setCommentCrawlProgress(prev => ({
                ...prev,
                [postId]: { status: 'running', message: 'Đang gửi yêu cầu cào...' }
            }));
            const activeCookie = cookie || localStorage.getItem('fb_cookie') || '';
            const activeDtsg = localStorage.getItem('fb_dtsg') || '';
            const res = await api.post('/facebook/crawl_comments', {
                post_id: postId,
                feedback_id: feedbackId || '',
                cookie: activeCookie,
                fb_dtsg: activeDtsg
            });
            if (res.data.status !== 'ok') {
                setCommentCrawlProgress(prev => ({
                    ...prev,
                    [postId]: { status: 'error', message: res.data.message || 'Lỗi khi yêu cầu cào' }
                }));
                return null;
            }

            return new Promise((resolve) => {
                const interval = setInterval(async () => {
                    try {
                        const sRes = await api.get(`/facebook/comment_status?post_id=${encodeURIComponent(postId)}`);
                        const p = sRes.data?.progress;
                        if (p) {
                            setCommentCrawlProgress(prev => ({
                                ...prev,
                                [postId]: { status: p.status, message: p.message || 'Đang cào...', total: p.total }
                            }));

                            if (p.status === 'done' || p.status === 'error') {
                                clearInterval(interval);
                                const newCommentsData = await fetchComments(postId);
                                loadData();
                                resolve(newCommentsData);
                            }
                        }
                    } catch (err) {
                        // ignore polling errors
                    }
                }, 1000);
            });
        } catch (e: any) {
            setCommentCrawlProgress(prev => ({
                ...prev,
                [postId]: { status: 'error', message: e.message || 'Lỗi mạng khi cào' }
            }));
            return null;
        }
    };

    const stopCommentCrawl = async (postId: string) => {
        try {
            await api.post('/facebook/stop_comment_crawl', { post_id: postId });
            setCommentCrawlProgress(prev => {
                const next = {
                    ...prev,
                    [postId]: { status: 'idle', message: 'Đã dừng cào bình luận.' }
                };
                sessionStorage.setItem('fb_comment_progress', JSON.stringify(next));
                return next;
            });
            loadData();
        } catch (e) {
            console.error('Failed to stop comment crawl:', e);
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

    const isLocalCommentRunning = Object.values(commentCrawlProgress).some(
        p => p.status === 'running' || p.status === 'queued'
    );
    const isCommentCrawling = backendIsCommentCrawling || feedCrawling || isLocalCommentRunning;

    return {
        crawling, data, statusText, statusColor, toastMessage, cookie, saveCookie,
        startCrawl, stopCrawl, loadData, fetchGroups,
        page, setPage, limit, setLimit, total,
        sort, order, changeSort,
        groups, groupIdFilter, groupNameFilter, selectGroup,
        statusFilter, setStatusFilter,
        startDateFilter, setStartDateFilter, endDateFilter, setEndDateFilter,
        selectedPosts, toggleSelection, toggleSelectAll,
        bulkRefresh, bulkCheckStatus, bulkCrawlComments, bulkExportCsv, bulkDelete,
        feedCrawling, fetchComments, setCookie,
        crawlPostComments, stopCommentCrawl, commentCrawlProgress, isCommentCrawling
    };
};
