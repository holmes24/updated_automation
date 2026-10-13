import { apiClient } from './client';
import type { Coordinator, PageMeta } from '../types';

export interface CoordinatorListParams {
  pc_id?: string;
  is_active?: boolean;
  page?: number;
  page_size?: number;
  search?: string;
}

export interface CoordinatorListResult extends PageMeta {
  coordinators: Coordinator[];
}

export async function listCoordinators(params?: CoordinatorListParams) {
  const { data } = await apiClient.get<CoordinatorListResult>('/coordinators', { params });
  return data;
}

export async function createCoordinator(payload: { name: string; phone_number?: string }) {
  const { data } = await apiClient.post<Coordinator>('/coordinators', payload);
  return data;
}

export async function updateCoordinator(
  pc_id: string,
  payload: Partial<Pick<Coordinator, 'name' | 'phone_number' | 'is_active'>>
) {
  const { data } = await apiClient.patch<Coordinator>(`/coordinators/${pc_id}`, payload);
  return data;
}
