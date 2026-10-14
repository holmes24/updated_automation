"""Unified AI attendance processing pipeline.

Performs verification inside the Redis worker, enforces a single submission
per calendar day in IST, validates the GPS photo timestamp, and logs flag reasons.
"""
import logging
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from app.db.mongodb import (
    create_notification,
    get_db,
    get_enrollment,
    has_submission_today,
    lookup_roster,
    normalize_phone,
)
from app.redis_queue import NOTIFICATION_STREAM, enqueue, get_redis
from app.schemas import InteraktWebhookPayload
from app.services.admin_alert import send_admin_alert
from app.services.alert_formatting import format_issues_for_alert
from app.services.duplicate_check import compute_image_hash, is_duplicate
from app.services.face_detect import detect_face
from app.services.face_match import verify_identity
from app.services.geofence import check_geofence
from app.services.liveness import check_passive_liveness
from app.services.ocr import extract_overlay_data
from app.services.shift_check import NON_FAILURE_STATUSES, check_shift_window
from app.services.whatsapp_reply import build_reply_message

logger = logging.getLogger("ingestion")
INDIA_TZ = ZoneInfo("Asia/Kolkata")


def _get_today_ist() -> str:
    """Calendar date in Indian Standard Time (YYYY-MM-DD)."""
    return datetime.now(INDIA_TZ).strftime("%Y-%m-%d")


async def download_media(media_url: str) -> bytes:
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(media_url)
        response.raise_for_status()
        return response.content


def _notification_id(event_id: str, kind: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"attendance:{event_id}:{kind}"))


async def _queue_notification(job: dict) -> None:
    mongo_job = dict(job)
    await create_notification(mongo_job)

    redis = get_redis()
    try:
        await enqueue(redis, NOTIFICATION_STREAM, job)
    finally:
        await redis.close()


async def queue_submission_notifications(
    event_id: str,
    payload: InteraktWebhookPayload,
    submission: dict,
) -> None:
    roster_name = submission.get("employee_name")
    verdict = submission.get("verdict")
    issues = submission.get("issues", [])

    reply = build_reply_message(verdict, roster_name, issues)
    await _queue_notification({
        "notification_id": _notification_id(event_id, "employee_reply"),
        "event_id": event_id,
        "kind": "employee_reply",
        "status": "pending",
        "attempt": 0,
        "country_code": payload.data.customer.country_code,
        "phone_number": payload.data.customer.phone_number,
        "message": reply,
    })

    if verdict != "verified":
        overlay = submission.get("overlay") or {}
        timestamp = overlay.get("timestamp")
        time_display = "Unknown"
        if timestamp:
            try:
                dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                time_display = dt.strftime("%d/%m/%Y, %I:%M %p")
            except ValueError:
                time_display = str(timestamp)
        await _queue_notification({
            "notification_id": _notification_id(event_id, "admin_alert"),
            "event_id": event_id,
            "kind": "admin_alert",
            "status": "pending",
            "attempt": 0,
            "employee_name": roster_name or f"Unknown ({submission.get('sender_phone')})",
            "site": submission.get("site_name") or "N/A",
            "issue_text": format_issues_for_alert(issues),
            "time_str": time_display,
        })


async def process_attendance_submission(
    payload: InteraktWebhookPayload,
    event_id: str,
) -> None:
    msg = payload.data.message
    if msg.message_content_type != "Image":
        logger.info("Ignoring non-image message from %s", payload.data.customer.channel_phone_number)
        return

    db = get_db()
    existing = await db.submissions.find_one({"event_id": event_id})
    if existing:
        existing["_id"] = str(existing["_id"])
        await queue_submission_notifications(event_id, payload, existing)
        return

    sender_phone = normalize_phone(payload.data.customer.channel_phone_number or payload.data.customer.phone_number)
    caption = msg.message or ""
    media_url = msg.media_url
    issues: list[str] = []
    today_ist = _get_today_ist()
    logger.info("Processing attendance submission from %s event=%s date=%s", sender_phone, event_id, today_ist)

    roster_entry = await lookup_roster(sender_phone)
    if roster_entry is None:
        issues.append("unregistered_phone_number")

    if roster_entry is not None and not roster_entry.is_active:
        if not media_url:
            return
        image_bytes = await download_media(media_url)
        new_hash = compute_image_hash(image_bytes)
        submission = {
            "event_id": event_id,
            "employee_id": roster_entry.employee_id,
            "employee_name": roster_entry.name,
            "person_role": roster_entry.role,
            "pc_id": roster_entry.pc_id,
            "parent_employee_id": roster_entry.parent_employee_id,
            "sender_phone": sender_phone,
            "caption": caption,
            "media_url": media_url,
            "image_hash": str(new_hash),
            "attendance_date": today_ist,
            "attendance_status": "absent",
            "verdict": "inactive_account",
            "review_status": "n/a",
            "issues": ["employee_inactive"],
            "flag_reason": "INACTIVE",
            "received_at_utc": msg.received_at_utc,
            "entry_type": "whatsapp",
        }
        await db.submissions.insert_one(submission)
        await queue_submission_notifications(event_id, payload, submission)
        return

    # Enforce exactly one submission attempt per day
    if roster_entry is not None and await has_submission_today(roster_entry.employee_id, today_ist):
        warning_job = {
            "notification_id": _notification_id(event_id, "employee_duplicate_day"),
            "event_id": event_id,
            "kind": "employee_reply",
            "status": "pending",
            "attempt": 0,
            "country_code": payload.data.customer.country_code,
            "phone_number": payload.data.customer.phone_number,
            "message": "⚠️ You've already submitted your attendance for today. If there's a problem with it, please contact your admin/supervisor.",
        }
        await _queue_notification(warning_job)
        return

    if not media_url:
        logger.error("No media_url in payload — cannot process image")
        return
    image_bytes = await download_media(media_url)

    overlay = extract_overlay_data(image_bytes)
    if not overlay.extraction_complete:
        issues.append("overlay_extraction_incomplete")

    # Validate photo capture date matches current day
    photo_date = None
    photo_timestamp_iso = None
    if overlay.timestamp is not None:
        photo_timestamp_iso = overlay.timestamp.isoformat()
        try:
            photo_date = overlay.timestamp.astimezone(INDIA_TZ).strftime("%Y-%m-%d")
        except Exception:
            photo_date = overlay.timestamp.strftime("%Y-%m-%d")

        if photo_date != today_ist:
            issues.append(f"date_mismatch_{photo_date}")
            logger.warning(
                "Photo date mismatch for %s: photo from %s, submitted on %s",
                sender_phone, photo_date, today_ist,
            )

    new_hash = compute_image_hash(image_bytes)
    if roster_entry:
        past_submissions = db.submissions.find({"employee_id": roster_entry.employee_id})
        async for past in past_submissions:
            if not past.get("image_hash"):
                continue
            dup, distance = is_duplicate(new_hash, past["image_hash"])
            if dup:
                issues.append(f"duplicate_of_submission_{past['_id']}")
                break

    geofence_passed = None
    geofence_distance = None
    if roster_entry and roster_entry.assigned_site and overlay.latitude is not None and overlay.longitude is not None:
        geofence_passed, geofence_distance = check_geofence(
            overlay.latitude, overlay.longitude,
            roster_entry.assigned_site.lat, roster_entry.assigned_site.long,
        )
        if not geofence_passed:
            issues.append(f"geofence_fail_{geofence_distance:.0f}m")
    elif roster_entry and not roster_entry.assigned_site:
        issues.append("assigned_site_not_configured")
    elif roster_entry and (overlay.latitude is None or overlay.longitude is None):
        issues.append("photo_gps_missing")

    face_present, face_count = detect_face(image_bytes)
    if not face_present:
        issues.append("no_face_detected")

    liveness_status, liveness_issues, liveness_metrics = check_passive_liveness(image_bytes)
    if liveness_status == "suspicious":
        issues.extend(f"liveness_{x}" for x in liveness_issues)

    identity_verdict = None
    identity_score = None
    if face_present and roster_entry:
        enrolled = await get_enrollment(roster_entry.employee_id)
        if not enrolled:
            issues.append("not_enrolled")
        else:
            identity_verdict, identity_score = verify_identity(image_bytes, enrolled)
            if identity_verdict != "verified":
                issues.append(f"identity_{identity_verdict}_{identity_score:.2f}")

    shift_status = None
    if overlay.timestamp is not None:
        shift_status, shift_reason = check_shift_window(
            overlay.timestamp,
            employee_shift_start=roster_entry.shift_start if roster_entry else None,
            employee_shift_end=roster_entry.shift_end if roster_entry else None,
            employee_grace_minutes=roster_entry.shift_grace_minutes if roster_entry else None,
        )
        if shift_status not in NON_FAILURE_STATUSES:
            issues.append(f"shift_{shift_status}")

    verdict = "verified" if not issues else "flagged"

    flag_reason = None
    if verdict == "flagged":
        if any(i.startswith("date_mismatch") for i in issues):
            flag_reason = "DATE"
        elif any("geofence" in i for i in issues):
            flag_reason = "LOCATION"
        elif any("face" in i or "identity" in i for i in issues):
            flag_reason = "FACE"
        elif any("duplicate" in i for i in issues):
            flag_reason = "DUPLICATE"
        elif any("shift" in i for i in issues):
            flag_reason = "SHIFT"
        else:
            flag_reason = "REVIEW"

    if verdict == "verified":
        attendance_status = "absent_late" if shift_status in ("after_grace", "after_window") else ("late" if shift_status == "late" else "present")
    else:
        attendance_status = "pending"

    submission = {
        "event_id": event_id,
        "employee_id": roster_entry.employee_id if roster_entry else None,
        "employee_name": roster_entry.name if roster_entry else None,
        "person_role": roster_entry.role if roster_entry else None,
        "pc_id": roster_entry.pc_id if roster_entry else None,
        "parent_employee_id": roster_entry.parent_employee_id if roster_entry else None,
        "sender_phone": sender_phone,
        "caption": caption,
        "media_url": media_url,
        "image_hash": str(new_hash),
        "overlay": overlay.model_dump(mode="json"),
        "site_name": roster_entry.assigned_site.name if roster_entry and roster_entry.assigned_site else None,
        "geofence_passed": geofence_passed,
        "geofence_distance_m": geofence_distance,
        "face_present": face_present,
        "face_count": face_count,
        "liveness_status": liveness_status,
        "liveness_issues": liveness_issues,
        "liveness_metrics": liveness_metrics,
        "identity_verdict": identity_verdict,
        "identity_score": identity_score,
        "shift_status": shift_status,
        "attendance_date": today_ist,
        "photo_date": photo_date,
        "photo_timestamp": photo_timestamp_iso,
        "attendance_status": attendance_status,
        "flag_reason": flag_reason,
        "verdict": verdict,
        "review_status": "n/a" if verdict == "verified" else "pending",
        "issues": issues,
        "entry_type": "whatsapp",
        "received_at_utc": msg.received_at_utc,
    }

    try:
        await db.submissions.insert_one(submission)
    except Exception as exc:
        if "duplicate key" not in str(exc).lower():
            raise
        submission = await db.submissions.find_one({"event_id": event_id})
        if not submission:
            raise

    if submission.get("_id") is not None:
        submission["_id"] = str(submission["_id"])

    await queue_submission_notifications(event_id, payload, submission)
    logger.info("Attendance event %s completed verdict=%s issues=%s", event_id, verdict, issues or "none")
    