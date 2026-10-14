import { useState } from 'react';
import axios from 'axios';
import { createCoordinator, updateCoordinator } from '../api/coordinators';
import type { Coordinator } from '../types';
import { AssignedSiteMap, type SiteValue } from './AssignedSiteMap';

const inputStyle = {
  background: 'var(--color-surface-sunken)',
  borderColor: 'var(--color-border)',
  color: 'var(--color-ink)',
};

export function CoordinatorFormModal({
  coordinator,
  onClose,
  onSaved,
}: {
  coordinator?: Coordinator;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(coordinator?.name ?? '');
  const [phoneDigits, setPhoneDigits] = useState((coordinator?.phone_number ?? '').replace(/^91/, '').slice(0, 10));
  const [saving, setSaving] = useState(false);
  const [site, setSite] = useState<SiteValue | undefined>(coordinator?.assigned_site ?? undefined);
  const [shiftStart, setShiftStart] = useState(coordinator?.shift_start ?? '');
  const [shiftEnd, setShiftEnd] = useState(coordinator?.shift_end ?? '');
  const [graceMinutes, setGraceMinutes] = useState(coordinator?.shift_grace_minutes?.toString() ?? '');
  const [error, setError] = useState<string | null>(null);

  const phoneValid = phoneDigits.length === 10;

  function handlePhoneChange(raw: string) {
    setPhoneDigits(raw.replace(/\D/g, '').slice(0, 10));
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const payload = {
        name,
        phone_number: `91${phoneDigits}`,
        assigned_site: site ?? null,
        shift_start: shiftStart || null,
        shift_end: shiftEnd || null,
        shift_grace_minutes: graceMinutes ? Number(graceMinutes) : null,
      };
      if (coordinator) {
        await updateCoordinator(coordinator.pc_id, payload);
      } else {
        await createCoordinator(payload);
      }
      onSaved();
    } catch (err) {
      const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
      setError(typeof detail === 'string' ? detail : 'Could not save. Check the details and try again.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div
        className="w-full max-w-2xl rounded-lg border p-6 max-h-[90vh] overflow-y-auto shadow-xl"
        style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface-raised)' }}
      >
        <h2 className="text-base font-medium mb-4" style={{ color: 'var(--color-ink)' }}>
          {coordinator ? `Edit ${coordinator.pc_id}` : 'New project co-ordinator'}
        </h2>

        <label className="block text-xs mb-1" style={{ color: 'var(--color-ink-muted)' }}>
          Name *
        </label>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value.replace(/[^a-zA-Z ]/g, ''))}
          className="w-full mb-4 px-3 py-2 rounded-md text-sm border"
          style={inputStyle}
        />

        <label className="block text-xs mb-1" style={{ color: 'var(--color-ink-muted)' }}>
          Phone *
        </label>
        <div
          className="flex items-center rounded-md border overflow-hidden"
          style={{ borderColor: inputStyle.borderColor, background: inputStyle.background }}
        >
          <span
            className="px-3 py-2 text-sm border-r"
            style={{ borderColor: inputStyle.borderColor, color: 'var(--color-ink-muted)' }}
          >
            +91
          </span>
          <input
            value={phoneDigits}
            onChange={(e) => handlePhoneChange(e.target.value)}
            inputMode="numeric"
            placeholder="10-digit number"
            className="flex-1 min-w-0 px-3 py-2 text-sm outline-none"
            style={{ background: 'transparent', color: 'var(--color-ink)' }}
          />
        </div>
        {phoneDigits.length > 0 && !phoneValid && (
          <p className="text-xs mt-1" style={{ color: 'var(--color-absent)' }}>
            Enter all 10 digits.
          </p>
        )}

        <div className="grid grid-cols-2 gap-3 my-4">
          <label className="block text-xs" style={{ color: 'var(--color-ink-muted)' }}>
            Shift start
            <input
              type="time"
              value={shiftStart}
              onChange={(e) => setShiftStart(e.target.value)}
              className="mt-1 w-full px-3 py-2 rounded-md text-sm border"
              style={inputStyle}
            />
          </label>
          <label className="block text-xs" style={{ color: 'var(--color-ink-muted)' }}>
            Shift end
            <input
              type="time"
              value={shiftEnd}
              onChange={(e) => setShiftEnd(e.target.value)}
              className="mt-1 w-full px-3 py-2 rounded-md text-sm border"
              style={inputStyle}
            />
          </label>
          <label className="block text-xs" style={{ color: 'var(--color-ink-muted)' }}>
            Grace period (minutes)
            <input
              type="number"
              min="0"
              value={graceMinutes}
              onChange={(e) => setGraceMinutes(e.target.value)}
              className="mt-1 w-full px-3 py-2 rounded-md text-sm border"
              style={inputStyle}
            />
          </label>
        </div>
        <div className="mb-4"><AssignedSiteMap site={site} onChange={setSite} /></div>

        {error && (
          <p className="text-xs mb-3" style={{ color: 'var(--color-absent)' }}>
            {error}
          </p>
        )}

        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-3 py-1.5 rounded-md text-sm" style={{ color: 'var(--color-ink-muted)' }}>
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={!name.trim() || !phoneValid || saving}
            className="px-3 py-1.5 rounded-md text-sm font-medium disabled:opacity-50"
            style={{ background: 'var(--color-accent)', color: 'white' }}
          >
            {saving ? 'Saving…' : coordinator ? 'Save changes' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}