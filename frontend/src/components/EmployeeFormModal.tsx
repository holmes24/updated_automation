import { useState } from 'react';
import axios from 'axios';
import { createEmployee, updateEmployee, type CreateEmployeePayload } from '../api/employees';
import type { Coordinator, Employee } from '../types';
import { AssignedSiteMap, type SiteValue } from './AssignedSiteMap';

const inputStyle = {
  background: 'var(--color-surface-sunken)',
  borderColor: 'var(--color-border)',
  color: 'var(--color-ink)',
};

export function EmployeeFormModal({
  employee,
  coordinators,
  onClose,
  onSaved,
}: {
  employee: Employee | null; // null = creating new
  coordinators: Coordinator[];
  onClose: () => void;
  onSaved: () => void;
}) {
  // Phone is stored/submitted as the full "91XXXXXXXXXX" form the backend
  // expects (matches sender_phone format seen in real records), but the
  // input itself only ever shows/accepts the 10 local digits — the +91 is
  // a fixed prefix, not something the user types.
  const initialLocalDigits = (employee?.phone_number ?? '').replace(/^91/, '').slice(0, 10);

  const [form, setForm] = useState<CreateEmployeePayload>({
    phone_number: employee?.phone_number ?? '',
    name: employee?.name ?? '',
    pc_id: employee?.pc_id ?? undefined,
    area: employee?.area ?? undefined,
    designation: employee?.designation ?? undefined,
    assigned_site: employee?.assigned_site ?? undefined,
    shift_start: employee?.shift_start ?? undefined,
    shift_end: employee?.shift_end ?? undefined,
    shift_grace_minutes: employee?.shift_grace_minutes ?? undefined,
  });
  const [phoneDigits, setPhoneDigits] = useState(initialLocalDigits);
  const [saving, setSaving] = useState(false);
  const [site, setSite] = useState<SiteValue | undefined>(employee?.assigned_site ?? undefined);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof CreateEmployeePayload>(key: K, value: CreateEmployeePayload[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function handlePhoneChange(raw: string) {
    const digitsOnly = raw.replace(/\D/g, '').slice(0, 10);
    setPhoneDigits(digitsOnly);
    set('phone_number', digitsOnly ? `91${digitsOnly}` : '');
  }

  function handleNameChange(raw: string) {
    // Letters and spaces only, per requirement — no digits or punctuation.
    set('name', raw.replace(/[^a-zA-Z ]/g, ''));
  }

  const phoneValid = phoneDigits.length === 10;

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const payload = { ...form, assigned_site: site };
      if (employee) {
        await updateEmployee(employee.employee_id, payload);
      } else {
        await createEmployee(payload);
      }
      onSaved();
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const detail = err.response?.data?.detail;
        const message = typeof detail === 'string'
          ? detail
          : Array.isArray(detail)
            ? detail.map((item: { msg?: string }) => item.msg ?? 'Invalid field').join('; ')
            : null;
        setError(message ?? (err.response?.status === 409
          ? 'This phone number is already registered. Edit the existing supervisor instead.'
          : `Could not save employee (HTTP ${err.response?.status ?? 'network error'}).`));
      } else {
        setError('Unexpected error while saving employee.');
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div
        className="w-full max-w-lg rounded-lg border p-6 max-h-[85vh] overflow-y-auto shadow-xl"
        style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface-raised)' }}
      >
        <h2 className="text-base font-medium mb-4" style={{ color: 'var(--color-ink)' }}>
          {employee ? `Edit ${employee.employee_id}` : 'New field supervisor'}
        </h2>

        <div className="grid grid-cols-2 gap-3 mb-3">
          <Field label="Name" required>
            <input
              value={form.name}
              onChange={(e) => handleNameChange(e.target.value)}
              className="w-full px-3 py-2 rounded-md text-sm border"
              style={inputStyle}
            />
          </Field>
          <Field label="Phone number" required>
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
            {employee && (
              <p className="text-xs mt-1" style={{ color: 'var(--color-ink-faint)' }}>
                Changing this re-points which WhatsApp number is matched to {employee.employee_id}.
              </p>
            )}
          </Field>
          <Field label="Coordinator">
            <select
              value={form.pc_id ?? ''}
              onChange={(e) => set('pc_id', e.target.value || undefined)}
              className="w-full px-3 py-2 rounded-md text-sm border"
              style={inputStyle}
            >
              <option value="">Unassigned</option>
              {coordinators.map((c) => (
                <option key={c.pc_id} value={c.pc_id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Area">
            <input
              value={form.area ?? ''}
              onChange={(e) => set('area', e.target.value || undefined)}
              className="w-full px-3 py-2 rounded-md text-sm border"
              style={inputStyle}
            />
          </Field>
          <Field label="Designation">
            <input
              value={form.designation ?? ''}
              onChange={(e) => set('designation', e.target.value || undefined)}
              className="w-full px-3 py-2 rounded-md text-sm border"
              style={inputStyle}
            />
          </Field>
          <Field label="Grace period (min)">
            <input
              type="number"
              value={form.shift_grace_minutes ?? ''}
              onChange={(e) => set('shift_grace_minutes', e.target.value ? Number(e.target.value) : undefined)}
              className="w-full px-3 py-2 rounded-md text-sm border"
              style={inputStyle}
            />
          </Field>
          <Field label="Shift start">
            <input
              type="time"
              value={form.shift_start ?? ''}
              onChange={(e) => set('shift_start', e.target.value || undefined)}
              className="w-full px-3 py-2 rounded-md text-sm border"
              style={inputStyle}
            />
          </Field>
          <Field label="Shift end">
            <input
              type="time"
              value={form.shift_end ?? ''}
              onChange={(e) => set('shift_end', e.target.value || undefined)}
              className="w-full px-3 py-2 rounded-md text-sm border"
              style={inputStyle}
            />
          </Field>
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
            disabled={saving || !form.name.trim() || !phoneValid}
            className="px-3 py-1.5 rounded-md text-sm font-medium disabled:opacity-50"
            style={{ background: 'var(--color-accent)', color: 'white' }}
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs mb-1" style={{ color: 'var(--color-ink-muted)' }}>
        {label}
        {required && ' *'}
      </label>
      {children}
    </div>
  );
}