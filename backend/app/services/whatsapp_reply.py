"""
Sends free-form text replies to employees via Interakt's Send Message API.

CONFIRMED working via live test against the real Interakt account:
  POST https://api.interakt.ai/v1/public/message/
  { "countryCode": "+91", "phoneNumber": "...", "type": "Text",
    "data": { "message": "..." } }
  -> {"result": true, "message": "Message queued...", "id": "..."}

Only works within the 24-hour session window (employee must have messaged
first) — which is always true here, since this fires in response to their
own selfie submission.
"""
import logging

import httpx

from app.config import settings

logger = logging.getLogger("whatsapp_reply")

INTERAKT_MESSAGE_URL = "https://api.interakt.ai/v1/public/message/"


async def send_text_reply(country_code: str, phone_number: str, message: str) -> bool:
    """
    Send a free-form text reply to an employee.

    Args:
        country_code: e.g. "+91" (matches Interakt's Customer.country_code field)
        phone_number: WITHOUT country code, e.g. "9123360859"
                      (matches Interakt's Customer.phone_number field —
                      do NOT pass the combined channel_phone_number here)
        message: plain text, sent as-is

    Returns True if Interakt accepted/queued the message, False otherwise.
    Never raises — a failed reply should not crash the pipeline; log and move on.
    """
    payload = {
        "countryCode": country_code,
        "phoneNumber": phone_number,
        "type": "Text",
        "data": {"message": message},
    }
    api_key = settings.interakt_api_key.strip()

    logger.info(
        "INTERAKT KEY INSIDE send_text_reply: loaded=%s length=%d",
        bool(api_key),
        len(api_key),
    )

    headers = {
        "Authorization": f"Basic {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                INTERAKT_MESSAGE_URL, json=payload, headers=headers, timeout=15.0
            )
        response.raise_for_status()
        result = response.json()
        if not result.get("result"):
            logger.warning("Interakt rejected reply to %s: %s", phone_number, result)
            return False
        logger.info("Reply sent to %s (message id: %s)", phone_number, result.get("id"))
        return True
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Failed to send reply to %s: %s — response body: %s",
            phone_number, exc, exc.response.text,
        )
        return False
    except Exception as exc:
        logger.error("Failed to send reply to %s: %s", phone_number, exc)
        return False


def build_reply_message(verdict: str, roster_name: str | None, issues: list[str]) -> str:
    """
    Human-readable reply text for the employee — plain language, not
    internal issue codes (those are for the admin alert / DB record).
    """
    if verdict == "verified":
        name = roster_name or "there"
        return f"✅ Attendance recorded, {name}. Thanks!"
    else:
        return (
            "⚠️ Your submission was received but needs review — "
            "it's been flagged for a supervisor to check. "
            "You don't need to resend unless asked."
        )