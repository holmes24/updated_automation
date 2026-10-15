import { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { deleteCoordinator, listCoordinators, updateCoordinator } from '../api/coordinators';
import type { Coordinator } from '../types';
import { CoordinatorFormModal } from '../components/CoordinatorFormModal';
import { Pencil, Trash2, UserX, UserCheck } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

const PAGE_SIZE = 25;

export function CoordinatorsPage() {
  const { canManage } = useAuth();
  const [coordinators, setCoordinators] = useState<Coordinator[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<Coordinator | 'new' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listCoordinators({ page, page_size: PAGE_SIZE, search: search || undefined });
      setCoordinators(data.coordinators);
      setTotal(data.total);
    } catch {
      setError('Could not load coordinators.');
    } finally {
      setLoading(false);
    }
  }, [page, search]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    setPage(1);
  }, [search]);

  async function toggleActive(c: Coordinator) {
    await updateCoordinator(c.pc_id, { is_active: !c.is_active });
    await load();
  }

  async function removeCoordinator(coordinator: Coordinator) {
    if (!window.confirm(`Delete coordinator ${coordinator.name} (${coordinator.pc_id})? Reassign all participants linked to this coordinator first. Historical attendance entries do not block deletion.`)) {
      return;
    }

    setDeletingId(coordinator.pc_id);
    setError(null);
    try {
      await deleteCoordinator(coordinator.pc_id);
      await load();
    } catch (err) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
      setError(typeof detail === 'string' ? detail : 'Could not delete coordinator. Please try again.');
    } finally {
      setDeletingId(null);
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-lg font-medium" style={{ color: 'var(--color-ink)' }}>
          Project Co-Ordinators
        </h1>
        {canManage && (
          <button
            onClick={() => setEditing('new')}
            className="px-3 py-1.5 rounded-md text-sm font-medium"
            style={{ background: 'var(--color-accent)', color: 'white' }}
          >
            Add project co-ordinator
          </button>
        )}
      </div>

      <div className="mb-5">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search name or phone…"
          className="px-3 py-1.5 rounded-md text-sm border w-64"
          style={{
            background: 'var(--color-surface-raised)',
            borderColor: 'var(--color-border)',
            color: 'var(--color-ink)',
          }}
        />
      </div>

      {canManage && editing && (
        <CoordinatorFormModal
          coordinator={editing === 'new' ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      )}

      {error && (
        <p role="alert" className="mb-4 text-sm" style={{ color: 'var(--color-flagged)' }}>
          {error}
        </p>
      )}

      <div className="rounded-lg border overflow-hidden shadow-sm" style={{ borderColor: 'var(--color-border)' }}>
        <table className="w-full text-sm">
          <thead>
            <tr style={{ background: 'var(--color-surface-sunken)' }}>
              {['ID', 'Name', 'Phone', 'Status', ...(canManage ? ['Action'] : [])].map((h) => (
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
            {coordinators.map((c) => (
              <tr key={c.pc_id} className="border-t" style={{ borderColor: 'var(--color-border-subtle)' }}>
                <td className="px-4 py-2.5" style={{ color: 'var(--color-ink)' }}>
                  {c.pc_id}
                </td>
                <td className="px-4 py-2.5" style={{ color: 'var(--color-ink)' }}>
                  {c.name}
                </td>
                <td className="px-4 py-2.5" style={{ color: 'var(--color-ink-muted)' }}>
                  {c.phone_number ?? '—'}
                </td>
                <td
                  className="px-4 py-2.5"
                  style={{ color: c.is_active ? 'var(--color-present)' : 'var(--color-inactive)' }}
                >
                  {c.is_active ? 'Active' : `Inactive since ${c.deactivated_at ?? '—'}`}
                </td>
                <td className="px-4 py-2.5 text-right">
                  {canManage && <button
                    onClick={() => setEditing(c)}
                    className="p-1.5 rounded-md transition-colors hover:bg-[var(--color-accent-bg)]"
                    style={{ color: 'var(--color-accent)' }}
                    title="Edit coordinator profile"
                  >
                    <Pencil size={16} />
                  </button>}
                  {canManage && <button
                    onClick={() => toggleActive(c)}
                    className="p-1.5 rounded-md transition-colors hover:bg-black/5"
                    style={{ color: 'var(--color-ink-muted)' }}
                    title={c.is_active ? 'Deactivate' : 'Reactivate'}
                  >
                    {c.is_active ? <UserX size={16} /> : <UserCheck size={16} />}
                  </button>}
                  {canManage && <button
                    onClick={() => removeCoordinator(c)}
                    disabled={deletingId === c.pc_id}
                    className="p-1.5 rounded-md transition-colors hover:bg-black/5 disabled:opacity-40"
                    style={{ color: 'var(--color-flagged)' }}
                    title="Delete coordinator"
                    aria-label={`Delete coordinator ${c.name}`}
                  >
                    <Trash2 size={16} />
                  </button>}
                </td>
              </tr>
            ))}
            {!loading && coordinators.length === 0 && (
              <tr>
                <td colSpan={canManage ? 5 : 4} className="px-4 py-8 text-center text-sm" style={{ color: 'var(--color-ink-faint)' }}>
                  No coordinators match these filters.
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
    </div>
  );
}