import axios from 'axios';
import { apiClient } from './client';
import type { AttendanceGrid, AttendanceRole, AttendanceRecord, PageMeta, Verdict } from '../types';

export interface AttendanceListParams {
  employee_id?: string;
  pc_id?: string;
  verdict?: Verdict;
  date_from?: string; // YYYY-MM-DD
  date_to?: string;
  page?: number;
  page_size?: number;
  search?: string;
}

export interface AttendanceListResult extends PageMeta {
  records: AttendanceRecord[];
}

export async function listAttendance(params?: AttendanceListParams) {
  const { data } = await apiClient.get<AttendanceListResult>('/attendance', { params });
  return data;
}

export async function resolveAttendance(
  submission_id: string,
  decision: 'approved' | 'rejected',
  reason?: string
) {
  const { data } = await apiClient.patch<AttendanceRecord>(
    `/attendance/${submission_id}/resolve`,
    { decision, reason }
  );
  return data;
}

export async function deleteAttendance(submission_id: string) {
  await apiClient.delete(`/attendance/${submission_id}`);
}

export async function getAttendanceGrid(params: {
  month: number;
  year: number;
  role?: AttendanceRole;
  pc_id?: string;
}) {
  const { data } = await apiClient.get<AttendanceGrid>('/attendance/grid', { params });
  return data;
}

export async function searchAttendancePeople(search: string, page_size = 20) {
  const { data } = await apiClient.get<{ people: import('../types').Employee[]; total: number }>(
    '/attendance/people',
    { params: { search, page_size } }
  );
  return data;
}

export async function overrideAttendanceCell(payload: {
  employee_id: string;
  date: string;
  attendance_code: string;
  reason: string;
}) {
  const { data } = await apiClient.patch('/attendance/override', payload);
  return data;
}

// --- Manual entry ---------------------------------------------------------
// POST /attendance/manual is the deliberate backdoor for when the WhatsApp/
// AI pipeline fails. A 409 means a submission already exists for this
// employee+date (any verdict) — the caller should redirect the admin to
// resolving that existing record instead, not silently fail.

export interface ManualEntryPayload {
  employee_id: string;
  date: string; // YYYY-MM-DD
  reason: string; // required, no default — backend rejects with 422 if missing
}

export class DuplicateSubmissionError extends Error {
  constructor() {
    super('A submission already exists for this employee on this date.');
    this.name = 'DuplicateSubmissionError';
  }
}

export async function createManualEntry(payload: ManualEntryPayload) {
  try {
    const { data } = await apiClient.post<AttendanceRecord>('/attendance/manual', payload);
    return data;
  } catch (err) {
    if (axios.isAxiosError(err) && err.response?.status === 409) {
      throw new DuplicateSubmissionError();
    }
    throw err;
  }
}

// --- Export ----------------------------------------------------------------

export interface ExportParams {
  month?: number;
  year?: number;
  date_from?: string;
  date_to?: string;
  pc_id?: string;
}

// Excel export can't go through a normal fetch-and-parse call — it's a
// binary file download, so we ask axios for a blob and hand the browser a
// synthetic <a download> click. Filename comes from the params since the
// backend doesn't echo one back for us to read easily cross-origin.
export async function downloadExport(params: ExportParams) {
  const { data } = await apiClient.get('/attendance/export', {
    params,
    responseType: 'blob',
  });
  const url = window.URL.createObjectURL(new Blob([data]));
  const link = document.createElement('a');
  link.href = url;
  const label = params.month
    ? `attendance_${params.year}-${String(params.month).padStart(2, '0')}`
    : `attendance_${params.date_from}_to_${params.date_to}`;
  link.download = `${label}${params.pc_id ? `_${params.pc_id}` : ''}.xlsx`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}
