"""Small recovery policy shared by transport and queue; no automatic full restarts."""
from email.utils import parsedate_to_datetime
import math
import time


def retry_delay(value, now=None):
    now = time.time() if now is None else now
    try:
        result = float(value)
    except (TypeError, ValueError):
        try:
            result = parsedate_to_datetime(value).timestamp() - now
        except (TypeError, ValueError, OverflowError):
            return 5.0
    return max(0.0, result) if math.isfinite(result) else 5.0


def can_retry(kind, attempts, checkpoint):
    return (kind in {'transient', 'expired'} and attempts < 2
            and (not checkpoint.get('offset') or bool(checkpoint.get('etag')))
            and checkpoint.get('phase') != 'invalid')
