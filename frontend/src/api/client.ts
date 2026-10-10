import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
});

export const getRequests = async (params: any = {}) => {
  const { data } = await api.get('/requests', { params });
  return data;
};

export const getRequestDetails = async (id: string | number) => {
  const { data } = await api.get(`/requests/${id}`);
  return data;
};

export const getStats = async () => {
  const { data } = await api.get('/stats');
  return data;
};

export const getDomains = async () => {
  const { data } = await api.get('/domains');
  return data;
};

export const getConfig = async () => {
  const { data } = await api.get('/config');
  return data;
};

export const toggleDb = async (enabled?: boolean, allowed_domains?: string[]) => {
  const payload: any = {};
  if (enabled !== undefined) payload.enabled = enabled;
  if (allowed_domains !== undefined) payload.allowed_domains = allowed_domains;
  const { data } = await api.post('/toggle_db', payload);
  return data;
};

export const exportRequests = (format: string, ids?: number[]) => {
  let url = `/api/export/${format}`;
  if (ids && ids.length > 0) {
    url += `?ids=${ids.join(',')}`;
  }
  window.open(url, '_blank');
};

export default api;
