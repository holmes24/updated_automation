"""Run one instance: python -m app.absence_worker"""
import asyncio
import logging
from app.services.absence_finalizer import finalize_absences

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('absence_worker')

async def run():
    while True:
        try:
            await finalize_absences()
        except Exception:
            logger.exception('Attendance absence finalization failed')
        await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nAttendance worker stopped by user.")
