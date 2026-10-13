import { useState } from 'react';
import { createCoordinator } from '../api/coordinators';

const inputStyle = {
  background: 'var(--color-surface-sunken)',
  borderColor: 'var(--color-border)',
  color: 'var(--color-ink)',
};

export function CoordinatorFormModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState('');
  const [phoneDigits, setPhoneDigits] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const phoneValid = phoneDigits.length === 10;

  function handlePhoneChange(raw: string) {
    setPhoneDigits(raw.replace(/\D/g, '').slice(0, 10));
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await createCoordinator({ name, phone_number: `91${phoneDigits}` });
      onSaved();
    } catch {
      setError('Could not save. Check the details and try again.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4">
      <div
        className="w-full max-w-sm rounded-lg border p-6 shadow-xl"
        style={{ borderColor: 'var(--color-border)', background: 'var(--color-surface-raised)' }}
      >
        <h2 className="text-base font-medium mb-4" style={{ color: 'var(--color-ink)' }}>
          New coordinator
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

        <div className="mb-4" />

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
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}