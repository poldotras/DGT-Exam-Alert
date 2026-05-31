"""Time helpers — Europe/Madrid timezone conversions.

Log timestamps are forced to UTC (see bootstrap.setup_logger); these helpers are for
user-facing displays (Telegram) and the 'expired exam' date arithmetic, which must run
in local Madrid time.
"""
from datetime import date, datetime

import pytz

MADRID_TZ = pytz.timezone("Europe/Madrid")


def now_madrid() -> datetime:
    """Return the current datetime in Europe/Madrid timezone (tz-aware)."""
    return datetime.now(MADRID_TZ)


def today_madrid() -> date:
    """Return today's date in Europe/Madrid timezone."""
    return now_madrid().date()
