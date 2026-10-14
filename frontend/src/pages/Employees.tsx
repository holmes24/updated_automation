import { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { deleteEmployee, listEmployees, updateEmployee } from '../api/employees';
import { listCoordinators } from '../api/coordinators';
import type { Coordinator, Employee } from '../types';
import { EmployeeFormModal } from '../components/EmployeeFormModal';
import { EnrollFaceModal } from '../components/EnrollFaceModal';
import { ScanFace, Pencil, Trash2, UserX, UserCheck } from 'lucide-react';

const PAGE_SIZE = 25;

export function EmployeesPage() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [coordinators, setCoordinators] = useState<Coordinator[]>([]);
  const [fieldSupervisors, setFieldSupervisors] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pcFilter, setPcFilter] = useState('');
  const [showInactive, setShowInactive] = useState(false);
  const [search, setSearch] = useState('');
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const [editing, setEditing] = useState<Employee | null | 'new'>(null);
  const [enrolling, setEnrolling] = useState<Employee | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listEmployees({
        pc_id: pcFilter || undefined,
        is_active: showInactive ? undefined : true,
        search: search || undefined,
        page,
        page_size: PAGE_SIZE,
      });
      setEmployees(data.employees);
      setTotal(data.total);
    } catch {
      setError('Could not load attendance participants.');
    } finally {
      setLoading(false);
    }
  }, [pcFilter, showInactive, search, page]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setPage(1);
  }, [pcFilter, showInactive, search]);

  useEffect(() => {
    listCoordinators({ page_size: 500 }).then((r) => setCoordinators(r.coordinators));
    listEmployees({ role: 'FS', page_size: 500 })
      .then((r) => setFieldSupervisors(r.employees))
      .catch(() => setError('Could not load field supervisor reporting options.'));
  }, []);

  async function toggleActive(emp: Employee) {
    await updateEmployee(emp.employee_id, { is_active: !emp.is_active });
    await load();
  }

  async function removeEmployee(employee: Employee) {
    if (!window.confirm(`Permanently delete ${employee.name} (${employee.employee_id})? This is only allowed when there is no attendance history or child assignment.`)) {
      return;
    }

    setDeletingId(employee.employee_id);
    setError(null);
    try {
      await deleteEmployee(employee.employee_id);
      await load();
    } catch (err) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
      setError(typeof detail === 'string' ? detail : 'Could not delete participant. Please try again.');
    } finally {
      setDeletingId(null);
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-medium" style={{ color: 'var(--color-ink)' }}>
            Attendance Participants
          </h1>
          <p className="text-sm mt-0.5" style={{ color: 'var(--color-ink-muted)' }}>
            Set each person’s department and reporting line. Older records without a saved department default to FS.
          </p>
        </div>
        <button
          onClick={() => setEditing('new')}
          className="px-3 py-1.5 rounded-md text-sm font-medium"
          style={{ background: 'var(--color-accent)', color: 'white' }}
        >
          Add participant
        </button>
      </div>

      <div className="flex gap-2 mb-5 items-center flex-wrap">
        <select
          value={pcFilter}
          onChange={(e) => setPcFilter(e.target.value)}
          className="px-2 py-1.5 rounded-md text-sm border"
          style={{
            background: 'var(--color-surface-raised)',
            borderColor: 'var(--color-border)',
            color: 'var(--color-ink-muted)',
          }}
        >
          <option value="">All coordinators</option>
          {coordinators.map((c) => (
            <option key={c.pc_id} value={c.pc_id}>
              {c.name}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-1.5 text-sm" style={{ color: 'var(--color-ink-muted)' }}>
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
          Show inactive
        </label>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search name or phone…"
          className="px-2 py-1.5 rounded-md text-sm border ml-auto w-48"
          style={{
            background: 'var(--color-surface-raised)',
            borderColor: 'var(--color-border)',
            color: 'var(--color-ink)',
          }}
        />
      </div>

      {error && (
        <p role="alert" className="mb-4 text-sm" style={{ color: 'var(--color-flagged)' }}>
          {error}
        </p>
      )}

      <div className="rounded-lg border overflow-hidden shadow-sm" style={{ borderColor: 'var(--color-border)' }}>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ background: 'var(--color-surface-sunken)' }}>
              {['ID', 'Name', 'Department', 'Coordinator', 'Reports To', 'Area', 'Designation', 'Status', 'Action'].map((h) => (
                <th
                  key={h}
                  className={`px-4 py-2.5 text-xs font-medium ${h === 'Action' ? 'text-right' : 'text-left'}`}
                  style={{ color: 'var(--color-ink-faint)' }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {employees.map((emp) => (
              <tr key={emp.employee_id} className="border-t" style={{ borderColor: 'var(--color-border-subtle)' }}>
                <td className="px-4 py-2.5" style={{ color: 'var(--color-ink)' }}>
                  {emp.employee_id}
                </td>
                <td className="px-4 py-2.5" style={{ color: 'var(--color-ink)' }}>
                  {emp.name}
                </td>
                <td className="px-4 py-2.5" style={{ color: 'var(--color-ink-muted)' }}>
                  {emp.role}
                </td>
                <td className="px-4 py-2.5" style={{ color: 'var(--color-ink-muted)' }}>
                  {coordinators.find((c) => c.pc_id === emp.pc_id)?.name ?? '—'}
                </td>
                <td className="px-4 py-2.5" style={{ color: 'var(--color-ink-muted)' }}>
                  {emp.role === 'LS'
                    ? fieldSupervisors.find((supervisor) => supervisor.employee_id === emp.parent_employee_id)?.name ?? emp.parent_employee_id
                    : emp.role === 'FS' || emp.role === 'LSS'
                      ? coordinators.find((coordinator) => coordinator.pc_id === emp.pc_id)?.name ?? '—'
                      : '—'}
                </td>
                <td className="px-4 py-2.5" style={{ color: 'var(--color-ink-muted)' }}>
                  {emp.area ?? '—'}
                </td>
                <td className="px-4 py-2.5" style={{ color: 'var(--color-ink-muted)' }}>
                  {emp.designation ?? '—'}
                </td>
                <td
                  className="px-4 py-2.5"
                  style={{ color: emp.is_active ? 'var(--color-present)' : 'var(--color-inactive)' }}
                >
                  {emp.is_active ? 'Active' : `Inactive since ${emp.deactivated_at}`}
                </td>
                <td className="px-4 py-2.5 text-right">
                  <div className="flex items-center justify-end gap-1">
                    <button
                      onClick={() => setEnrolling(emp)}
                      className="p-1.5 rounded-md transition-colors hover:bg-[var(--color-accent-bg)]"
                      style={{ color: 'var(--color-accent)' }}
                      title="Enroll face"
                    >
                      <ScanFace size={16} />
                    </button>
                    <button
                      onClick={() => setEditing(emp)}
                      className="p-1.5 rounded-md transition-colors hover:bg-[var(--color-accent-bg)]"
                      style={{ color: 'var(--color-accent)' }}
                      title="Edit"
                    >
                      <Pencil size={16} />
                    </button>
                    <button
                      onClick={() => toggleActive(emp)}
                      className="p-1.5 rounded-md transition-colors hover:bg-black/5"
                      style={{ color: 'var(--color-ink-muted)' }}
                      title={emp.is_active ? 'Deactivate' : 'Reactivate'}
                    >
                      {emp.is_active ? <UserX size={16} /> : <UserCheck size={16} />}
                    </button>
                    <button
                      onClick={() => removeEmployee(emp)}
                      disabled={deletingId === emp.employee_id}
                      className="p-1.5 rounded-md transition-colors hover:bg-black/5 disabled:opacity-40"
                      style={{ color: 'var(--color-flagged)' }}
                      title="Delete participant"
                      aria-label={`Delete participant ${emp.name}`}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {!loading && employees.length === 0 && (
              <tr>
                <td colSpan={9} className="px-4 py-8 text-center text-sm" style={{ color: 'var(--color-ink-faint)' }}>
                  No attendance participants match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>

        {totalPages > 1 && (
          <div
            className="flex items-center justify-between px-4 py-2.5 border-t text-xs"
            style={{ borderColor: 'var(--color-border-subtle)', color: 'var(--color-ink-muted)' }}
          >
            <span>
              Page {page} of {totalPages}
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                className="px-2 py-1 rounded disabled:opacity-40"
                style={{ border: '1px solid var(--color-border)' }}
              >
                Previous
              </button>
              <button
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                className="px-2 py-1 rounded disabled:opacity-40"
                style={{ border: '1px solid var(--color-border)' }}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {editing && (
        <EmployeeFormModal
          employee={editing === 'new' ? null : editing}
          coordinators={coordinators}
          fieldSupervisors={fieldSupervisors}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      )}

      {enrolling && <EnrollFaceModal employee={enrolling} onClose={() => setEnrolling(null)} />}
    </div>
  );
}