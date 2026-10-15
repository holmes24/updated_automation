import axios from 'axios';
import { apiClient } from './client';
import type { AccountRole, LoginResponse, UserAccount } from '../types';

const baseURL = import.meta.env.VITE_API_BASE_URL ?? '/api';

// Deliberately a separate raw axios call, not apiClient: login is the one
// endpoint that takes X-API-Key instead of a Bearer token, and apiClient's
// interceptor would try (and fail) to attach a JWT we don't have yet.
const SHARED_API_KEY = import.meta.env.VITE_SHARED_API_KEY;

export async function login(username: string, password: string): Promise<LoginResponse> {
  const { data } = await axios.post<LoginResponse>(
    `${baseURL}/auth/login`,
    { username, password },
    { headers: { 'X-API-Key': SHARED_API_KEY } }
  );
  return data;
}

export async function getCurrentUser(): Promise<Pick<UserAccount, 'username' | 'role'>> {
  const { data } = await apiClient.get<Pick<UserAccount, 'username' | 'role'>>('/auth/me');
  return data;
}

export async function listUsers(): Promise<UserAccount[]> {
  const { data } = await apiClient.get<{ users: UserAccount[] }>('/auth/users');
  return data.users;
}

export async function registerUser(payload: {
  username: string;
  password: string;
  role: Extract<AccountRole, 'manual_team' | 'viewer'>;
}): Promise<UserAccount> {
  const { data } = await apiClient.post<UserAccount>('/auth/users', payload);
  return data;
}
