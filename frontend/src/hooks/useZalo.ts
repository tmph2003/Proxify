import { useState, useEffect, useRef } from 'react';
import api from '../api/client';

export const useZalo = () => {
    const [stats, setStats] = useState({ groups: 0, users: 0, memberships: 0 });
    const [jobs, setJobs] = useState<any[]>([]);
    const [groups, setGroups] = useState<any[]>([]);
    const [selectedGroup, setSelectedGroup] = useState<any | null>(null);
    const [members, setMembers] = useState<any[]>([]);
    const [search, setSearch] = useState('');
    const [toastMessage, setToastMessage] = useState('');
    const prevJobsRef = useRef<any[]>([]);

    const loadStats = async () => {
        try {
            const { data } = await api.get('/zalo/stats');
            setStats(data);
        } catch (e) {
            console.error(e);
        }
    };

    const loadJobs = async () => {
        try {
            const { data } = await api.get('/zalo/jobs');
            
            const prevJobs = prevJobsRef.current;
            for (const newJob of data) {
                if (newJob.status === 'completed') {
                    const oldJob = prevJobs.find((j: any) => j.id === newJob.id);
                    if (oldJob && (oldJob.status === 'pending' || oldJob.status === 'running')) {
                        setToastMessage(`✅ Hoàn thành: ${newJob.link}`);
                        setTimeout(() => setToastMessage(''), 4000);
                        
                        // Cũng tải lại danh sách nhóm để hiện nhóm mới cào
                        loadGroups();
                    }
                }
            }
            prevJobsRef.current = data;

            const activeJobs = data.filter((j: any) => j.status !== 'cancelled' && j.status !== 'completed');
            setJobs(activeJobs);
            return activeJobs;
        } catch (e) {
            console.error(e);
            return [];
        }
    };

    const loadGroups = async () => {
        try {
            const { data } = await api.get('/zalo/groups', { params: { search } });
            setGroups(data);
        } catch (e) {
            console.error(e);
        }
    };

    const selectGroup = async (groupId: string) => {
        try {
            const { data: groupData } = await api.get('/zalo/groups', { params: { search: groupId } });
            const group = groupData.find((g: any) => g.group_id === groupId);
            setSelectedGroup(group || { group_id: groupId });

            const { data: memberData } = await api.get(`/zalo/groups/${groupId}/members`);
            setMembers(memberData);
        } catch (e) {
            console.error(e);
        }
    };

    const cancelJob = async (jobId: number) => {
        try {
            await api.post(`/zalo/jobs/${jobId}/cancel`);
            await loadJobs();
        } catch (e) {
            console.error(e);
        }
    };

    const fetchZaloUrl = async (url: string) => {
        try {
            await api.post('/zalo/scan', { link: url });
            await loadJobs();
        } catch (e) {
            console.error(e);
        }
    };

    const fetchMembers = async (groupId: string) => {
        try {
            await api.post('/zalo/commands/fetch_members', { group_id: groupId });
            await loadJobs();
        } catch (e) {
            console.error(e);
            alert('Có lỗi xảy ra khi gửi lệnh.');
        }
    };

    useEffect(() => {
        loadStats();
        loadJobs();
        loadGroups();
        
        const interval = setInterval(async () => {
            loadStats();
            await loadJobs();
            
            // Auto reload members if selected group is active
            if (selectedGroup) {
                try {
                    const { data: memberData } = await api.get(`/zalo/groups/${selectedGroup.group_id}/members`);
                    setMembers(() => {
                        // Avoid flickering by only updating if lengths differ or deep equality checks fail. 
                        // Simplest is to just update. React handles virtual DOM.
                        return memberData;
                    });
                } catch(e) {}
            }
        }, 3000);
        return () => clearInterval(interval);
    }, [search, selectedGroup]);

    return {
        stats,
        jobs,
        groups,
        selectedGroup,
        members,
        search,
        toastMessage,
        setSearch,
        selectGroup,
        cancelJob,
        fetchZaloUrl,
        fetchMembers
    };
};
