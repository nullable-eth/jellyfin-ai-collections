"""Retry transient HTTP failures.

Jellyfin briefly drops out of its Service when its health check stalls; a
request in that window gets "connection refused". Waiting it out is better
than failing the whole run.
"""

from __future__ import annotations

import logging
import time
import urllib.error
from typing import Callable, TypeVar

T = TypeVar("T")
log = logging.getLogger("aicollections")

TRANSIENT_STATUS = {502, 503, 504}
DEFAULT_DELAYS = (5.0, 15.0, 30.0)


def is_transient(error: BaseException) -> bool:
    if isinstance(error, urllib.error.HTTPError):
        return error.code in TRANSIENT_STATUS
    # URLError (refused, DNS, reset) and socket timeouts.
    return isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError))


def with_retries(
    fn: Callable[[], T],
    what: str,
    delays: tuple[float, ...] = DEFAULT_DELAYS,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    for delay in (*delays, None):
        try:
            return fn()
        except Exception as e:
            if delay is None or not is_transient(e):
                raise
            log.warning("%s failed (%s); retrying in %.0fs", what, e, delay)
            sleep(delay)
    raise AssertionError("unreachable")
