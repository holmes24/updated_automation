# Attendance AI — Production Architecture

## Architecture

```text
WhatsApp / Interakt
       |
       v
Nginx + HTTPS
       |
       v
FastAPI (webhook/auth/admin APIs)
       |
       | Redis Streams
       v
Unified AI Worker(s)
  | OCR | Face | Geofence | Duplicate | Liveness
  v
MongoDB (system of record + audit)
       |
       v
Notification Stream
       |
       v
Notification Worker(s)
       |
       v
WhatsApp / Admin
```

FastAPI never performs the expensive attendance AI pipeline synchronously. Redis Streams provides buffering, consumer-group distribution, retry and dead-letter transport. MongoDB stores every submission, including suspicious additional submissions for audit.

## Attendance states

- **P** — Present
- **L** — Present but late
- **F** — Flagged and awaiting admin review
- **A** — Absent
- **N/A** — Employee inactive
- **Blank** — Today/future with no submission yet (export grid)

An approved flagged submission counts as P/L; a rejected flagged submission counts as A.

## Fraud and evidence checks

Each image submission is independently analyzed, even if another submission already exists for the same employee/day. Evidence includes:

- server/WhatsApp `received_at_utc` as authoritative attendance time
- OCR-visible date/time comparison against received date
- EXIF date as supporting evidence only
- SHA-256 exact-image hash
- source and normalized pHash
- previous submission reference and similarity/distance
- possible date/time-edit signal when a near-identical previous image has conflicting overlay dates
- face presence/count and enrolled-identity verification
- assigned-site geofence
- passive image-quality/liveness risk signals
- human-readable fraud flags

A still image cannot prove hardware-backed real-time liveness; suspicious passive signals are therefore review flags, not a liveness guarantee.

## Prerequisites on Windows

- Python **3.12**
- Node.js **20+**
- MongoDB **7/8** locally or a reachable MongoDB deployment
- Redis **7/8** locally
- Tesseract OCR
- Git is optional

Docker is optional for local development. Production deployment can use the supplied Docker Compose configuration.

## Fresh Windows PowerShell setup

```powershell
cd <extracted-folder>

cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
Copy-Item .env.example .env
pip install -r requirements.txt
```

Edit `backend\.env` and set the real credentials. Do not commit `.env`.

Install frontend dependencies:

```powershell
cd ..rontend
npm install
```

## Start local services

Start MongoDB using your installed MongoDB service/application.

Start Redis using your local Redis installation. If Redis is installed as a Windows service, start that service. If using WSL, run Redis inside WSL. Docker is optional:

```powershell
docker run -d --name attendance-redis -p 127.0.0.1:6379:6379 redis:8-alpine redis-server --appendonly yes
```

Then use separate PowerShell terminals:

```powershell
# Terminal 1 - API
cd <project>ackend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```powershell
# Terminal 2 - AI worker
cd <project>ackend
.\.venv\Scripts\Activate.ps1
$env:WORKER_CONSUMER_NAME="attendance-worker-1"
python -m app.worker
```

```powershell
# Terminal 3 - notification worker
cd <project>ackend
.\.venv\Scripts\Activate.ps1
$env:NOTIFICATION_CONSUMER_NAME="notification-worker-1"
python -m app.notification_worker
```

```powershell
# Terminal 4 - React
cd <project>rontend
npm run dev
```

Open `http://localhost:5173`.

For multiple AI workers, run another `python -m app.worker` with a different `WORKER_CONSUMER_NAME`. Redis Streams consumer groups distribute messages safely.

## Tesseract

Install Tesseract OCR and set:

```text
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

If `tesseract.exe` is on PATH, leave `TESSERACT_CMD` empty.

## MongoDB indexes

FastAPI startup calls `ensure_indexes()` and safely creates/updates indexes for roster, submissions, image fingerprints, webhook idempotency and notification jobs. Existing collections/data are not dropped.

## Production HTTPS / Nginx

The production flow is:

```text
https://your-domain/
https://your-domain/webhook/interakt
```

Nginx terminates TLS and proxies the webhook/admin traffic to FastAPI. Use a real certificate and domain; do not use ngrok as the production ingress.

The supplied `deploy/docker-compose.production.yml` starts backend, one or more workers, notification worker, frontend, Nginx, Redis and MongoDB.

## WhatsApp / Interakt

Configure Interakt to POST signed `message_received` webhooks to:

```text
https://YOUR_DOMAIN/webhook/interakt
```

Set `INTERAKT_WEBHOOK_SECRET` and `INTERAKT_API_KEY` only in `.env`/secret storage.

## Admin review

The React Attendance page shows P/L/F/A/N/A status for returned submission records and exposes human-readable reasons. Flagged records can be approved or rejected. Review details include server received time, OCR time, geofence, liveness and duplicate/reuse evidence. Face embedding vectors are never returned to the frontend.

## Fraud test checklist

1. Valid current photo, correct person/location -> **P**
2. Valid photo after shift grace -> **L**
3. Wrong person -> **F**
4. Wrong GPS -> **F**
5. Previous-day photo -> **F**
6. Exact same image again -> first result retained; second submission **F** and audited
7. Resized/recompressed near-duplicate -> **F** when pHash remains within threshold
8. Current-looking edited date over an old near-identical photo -> **F / possible_date_edit** when evidence supports it
9. Blurry photo -> **F**
10. No face -> **F**
11. Multiple faces -> **F**
12. Suspicious passive liveness/image characteristics -> **F**
13. No submission on a past day -> **A** in the export grid
14. Inactive employee -> **N/A**
15. Admin approval of F -> P/L; rejection -> A

## Troubleshooting

- `degraded` health: check MongoDB and Redis connectivity.
- Redis connection refused: verify Redis is listening on `127.0.0.1:6379` and `REDIS_URL`.
- OCR unavailable: verify Tesseract installation and `TESSERACT_CMD`.
- Face model startup errors: verify `insightface` and `onnxruntime` installation and the model runtime supported by the host.
- Webhook 401: verify the exact Interakt signature header/secret configuration.
- Workers not consuming: verify Redis is reachable and that all workers use the same stream/group but unique consumer names.
