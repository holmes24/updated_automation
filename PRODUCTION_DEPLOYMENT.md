# Production deployment

## Target architecture

```text
WhatsApp / Interakt
        |
        | HTTPS + Interakt signature
        v
      Nginx
        |
        v
     FastAPI
        |
        | Redis Stream: attendance:jobs
        v
 Unified AI Worker(s)
   |       |       |
   |       |       +--> MongoDB (submission + audit)
   |       |
   |       +----------> Redis Stream: attendance:notifications
   |                              |
   |                              v
   |                    Notification Worker(s)
   |                              |
   +------------------------------+--> Interakt

MongoDB = system of record
Redis = durable work transport / back-pressure / retry queue
Nginx = public TLS termination; ngrok is not used in production
```

## 1. Install dependencies

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Redis locally:

```powershell
docker run -d --name attendance-redis -p 127.0.0.1:6379:6379 redis:8-alpine redis-server --appendonly yes
```

## 2. Configure `.env`

Copy `backend/.env.example` to `backend/.env` and replace every placeholder.
Never commit `.env`.

For production containers, the internal URLs are typically:

```text
REDIS_URL=redis://redis:6379/0
MONGODB_URL=mongodb://<app-user>:<password>@mongo:27017/attendance_agent?authSource=admin
ENVIRONMENT=production
CORS_ORIGINS=https://attendance.example.com
```

Use a dedicated MongoDB application user rather than the MongoDB root user for the application.

## 3. Run the services

Local development:

```powershell
# terminal 1
cd backend
.\.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000

# terminal 2
cd backend
.\.venv\Scripts\activate
python -m app.worker

# terminal 3
cd backend
.\.venv\Scripts\activate
python -m app.notification_worker

# terminal 4
cd frontend
npm install
npm run dev
```

Production Docker:

```bash
cd deploy
docker compose --env-file ../backend/.env -f docker-compose.production.yml build
docker compose --env-file ../backend/.env -f docker-compose.production.yml up -d
```

The frontend build embeds `APP_API_KEY` in its browser bundle. Treat it as public; it is not a secret.

Before starting Nginx, provision the TLS certificate for your real domain and mount it at the paths in `deploy/nginx.conf`.

## 4. Production HTTPS

Point DNS `attendance.example.com` to the production server. Open ports 80 and 443 only. Nginx redirects HTTP to HTTPS and proxies `/webhook/interakt` to FastAPI.

The Interakt webhook URL becomes:

```text
https://attendance.example.com/webhook/interakt
```

There is no ngrok dependency in production.

## 5. Backups

Use `scripts/backup_mongodb.ps1` on Windows or an equivalent scheduled `mongodump` job on Linux. Store backups outside the MongoDB host, encrypt them, and periodically test restoration.

The backup must include at least:

- `roster`
- `submissions`
- `face_embeddings`
- `webhook_events`
- `notifications`
- `admin_users`
- `coordinators`
- `counters`

## 6. Worker scaling

Run more than one `app.worker` process using the same Redis consumer group and different `WORKER_CONSUMER_NAME` values. Redis Streams will distribute jobs across consumers.

Do the same for `app.notification_worker` with different `NOTIFICATION_CONSUMER_NAME` values.

## 7. Anti-spoofing note

The included liveness check is a passive risk/quality guard. A single WhatsApp still image cannot prove real-time human presence. It deliberately flags suspicious images rather than claiming cryptographic liveness.

For a stronger production control, the next phase should add a trained face anti-spoofing model or a short challenge video/interactive capture flow.
