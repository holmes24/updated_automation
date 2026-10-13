# Attendance AI Backend

The backend is the FastAPI ingress/admin API plus Redis Streams workers.

See the repository root `README.md` for the complete fresh Windows setup, architecture, fraud-test checklist and production deployment instructions.

## Processes

- `uvicorn app.main:app` — FastAPI webhook/auth/admin API
- `python -m app.worker` — unified attendance AI worker
- `python -m app.notification_worker` — durable WhatsApp/admin notification worker

The webhook only validates the signature, persists the idempotency event and enqueues a Redis Stream job. OCR, face verification, geofence, duplicate/reuse detection, passive liveness and attendance classification run in the worker.

## Configuration

Copy `.env.example` to `.env`. Secrets are never committed. Tesseract is configured with `TESSERACT_CMD`; no Windows path is hardcoded.

## Data safety

MongoDB is the system of record. Existing collections are preserved. Every image submission is retained for audit, including additional submissions made after a valid attendance result. Fraud evidence stores image fingerprints and references to previous submissions rather than exposing face embeddings to the frontend.
