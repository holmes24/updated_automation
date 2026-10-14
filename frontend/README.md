# Attendance Admin

React + TypeScript + Vite + Tailwind admin console for the WhatsApp attendance
verification backend.

## Setup

```bash
npm install
cp .env.example .env.local
```

Fill in `VITE_SHARED_API_KEY` in `.env.local` — this is the `X-API-Key` value
`/auth/login` expects (ask whoever holds the backend config for it).

```bash
npm run dev
```

Runs on `http://localhost:5173`. API calls go through the dev proxy
(`vite.config.ts`) to `http://localhost:8000` — change the `target` there if
your backend runs elsewhere locally.

## What's built (v1 scope)

- **Login** — single shared admin login (no PC-scoped accounts yet — see below)
- **Attendance** — filter by verdict/coordinator/date range, search by
  name/phone, real pagination, resolve flagged submissions (approve ->
  Present, reject -> Absent), log a manual entry (the deliberate backdoor for
  when the WhatsApp pipeline fails), trigger Excel export
- **Field Supervisors (Employees)** — list/filter/search, pagination, create,
  edit, enroll face (1-5 reference photos), activate/deactivate, and delete
  only when no attendance history exists
- **Coordinators (PCs)** — list/search, pagination, create, activate/deactivate,
  and delete only when no field supervisors are assigned
- **Activate/deactivate** — reversible status change that retains the record
  and history; submissions from inactive supervisors are flagged for review
- **Config-driven, not hardcoded** — thresholds (geofence radius, shift grace,
  etc.) are fetched once from `GET /config` on login via `ConfigContext`
  rather than baked into the UI as constants
- **No face-match score anywhere** — by explicit backend policy, the UI never
  shows `identity_score` or a percentage/progress-bar, only pass/fail-style
  labels (`FaceMatchStatus` in `components/StatusBadge.tsx`)

## Known gap, flagged not guessed

- **`identity_verdict`'s value set isn't documented yet.** `FaceMatchStatus`
  renders it as a plain neutral-styled label rather than color-coding it,
  because we don't know what values it actually takes. Once backend confirms
  the enum, turn that into a proper switch like the other badges.

## Deliberately not built yet

- **PC-scoped views.** The backend's `AdminUser.pc_id` and `role` fields exist
  but aren't enforced by any endpoint — every login currently sees
  everything. This frontend doesn't pretend otherwise: there's no "my PC's
  data only" filtering baked in. When PC-scoped auth actually lands
  server-side, the natural place to wire it in is `AuthContext` (decode the
  JWT's `pc_id` claim) plus default-filtering the list calls in `api/*.ts`.
- **`assigned_site` editing.** Geofence center (lat/long) isn't in the
  employee form yet — noted inline in the form. Add a map picker or plain
  lat/long fields to `EmployeeFormModal` when that's ready to build.
- **Coordinator assigned-sites rollup.** Deliberately cut for v1 — would need
  an N-lookup aggregation across all of a coordinator's employees; revisit
  only if it comes up post-demo, and push for backend to precompute/cache it
  rather than doing it client-side.
- **Token refresh.** Tokens expire after 60 min server-side; there's no
  refresh flow, just a 401 -> redirect-to-login on the next request
  (`api/client.ts`). Fine for an internal tool with short sessions; revisit
  if that gets annoying in practice.

## Structure

```
src/
  api/          one file per backend resource, thin wrappers over axios
  types/        TS interfaces mirroring backend response shapes exactly
  context/      AuthContext (token in localStorage + React state)
  components/   shared UI: Layout, StatusBadge, modals
  pages/        one per route: Login, Attendance, Employees, Coordinators
```
