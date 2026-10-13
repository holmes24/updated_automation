import { useMemo, useState } from 'react';
import { apiClient } from '../api/client';

export interface SiteValue {
  name: string;
  lat: number;
  long: number;
}

export function AssignedSiteMap({ site, onChange }: { site?: SiteValue; onChange: (site: SiteValue | undefined) => void }) {
  const [photoBusy, setPhotoBusy] = useState(false);
  const [photoMessage, setPhotoMessage] = useState('');
  async function uploadPhoto(file?: File) {
    if (!file) return;
    setPhotoBusy(true); setPhotoMessage('');
    try {
      const data = new FormData(); data.append('file', file);
      const response = await apiClient.post('/sites/extract-photo', data);
      const result = response.data as SiteValue;
      onChange({ name: result.name, lat: result.lat, long: result.long });
      setPhotoMessage('Coordinates extracted. Verify the map and edit if needed before saving.');
    } catch { setPhotoMessage('Could not extract GPS. Enter coordinates manually.'); }
    finally { setPhotoBusy(false); }
  }
  const valid = site && Number.isFinite(site.lat) && Number.isFinite(site.long) && site.lat >= -90 && site.lat <= 90 && site.long >= -180 && site.long <= 180;
  const mapUrl = useMemo(() => {
    if (!valid) return null;
    const d = 0.006;
    const { lat, long } = site!;
    return `https://www.openstreetmap.org/export/embed.html?bbox=${long - d}%2C${lat - d}%2C${long + d}%2C${lat + d}&layer=mapnik&marker=${lat}%2C${long}`;
  }, [valid, site?.lat, site?.long]);

  function locate() {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (position) => onChange({ name: site?.name || 'Assigned site', lat: position.coords.latitude, long: position.coords.longitude }),
      () => {},
      { enableHighAccuracy: true, timeout: 10000 }
    );
  }

  return (
    <div className="col-span-2 rounded-md border p-3" style={{ borderColor: 'var(--color-border)' }}>
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className="text-xs font-medium" style={{ color: 'var(--color-ink)' }}>Assigned site / geofence</div>
          <div className="text-[11px]" style={{ color: 'var(--color-ink-faint)' }}>This is the center used by the backend geofence check.</div>
        </div>
        <button type="button" onClick={locate} className="px-2 py-1 rounded border text-xs" style={{ borderColor: 'var(--color-border)' }}>
          Use my location
        </button>
      </div>
      <label className="block text-xs mb-2">Optional: upload GPS Map Camera photo
        <input type="file" accept="image/jpeg,image/png,image/webp" disabled={photoBusy} onChange={e => void uploadPhoto(e.target.files?.[0])} className="block w-full mt-1" />
      </label>
      {photoMessage && <p className="text-xs mb-2" role="status">{photoMessage}</p>}
      <div className="grid grid-cols-3 gap-2 mb-2">
        <input value={site?.name ?? ''} onChange={(e) => onChange({ name: e.target.value, lat: site?.lat ?? 0, long: site?.long ?? 0 })} placeholder="Site name" className="px-2 py-1.5 rounded border text-sm col-span-3" />
        <input type="number" step="any" value={site?.lat ?? ''} onChange={(e) => onChange({ name: site?.name ?? '', lat: Number(e.target.value), long: site?.long ?? 0 })} placeholder="Latitude" className="px-2 py-1.5 rounded border text-sm" />
        <input type="number" step="any" value={site?.long ?? ''} onChange={(e) => onChange({ name: site?.name ?? '', lat: site?.lat ?? 0, long: Number(e.target.value) })} placeholder="Longitude" className="px-2 py-1.5 rounded border text-sm" />
        <button type="button" onClick={() => onChange(undefined)} className="px-2 py-1.5 rounded border text-sm" style={{ borderColor: 'var(--color-border)' }}>Clear</button>
      </div>
      {mapUrl ? (
        <iframe title="Assigned site map" src={mapUrl} className="w-full h-48 rounded border" style={{ borderColor: 'var(--color-border)' }} />
      ) : (
        <div className="h-24 rounded border flex items-center justify-center text-xs" style={{ borderColor: 'var(--color-border)', color: 'var(--color-ink-faint)' }}>
          Enter valid latitude and longitude to preview the assigned site.
        </div>
      )}
    </div>
  );
}
