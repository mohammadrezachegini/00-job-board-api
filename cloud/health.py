import logging
import time

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from cloud.queue import get_queue

logger = logging.getLogger(__name__)


@never_cache
@require_GET
def healthz(request):
    return JsonResponse({"status": "ok"})


def _check_database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()


def _check_cache():
    cache.set("health:ping", "pong", timeout=5)
    if cache.get("health:ping") != "pong":
        raise RuntimeError("cache read-back mismatch")


def _check_queue():
    get_queue().ping()


CHECKS = [
    ("database", _check_database, True),
    ("cache", _check_cache, False),
    ("queue", _check_queue, False),
]


@never_cache
@require_GET
def readyz(request):
    checks = {}
    ready = True
    for name, check, critical in CHECKS:
        started = time.monotonic()
        try:
            check()
            result = {"status": "ok"}
        except Exception as exc:
            logger.warning("Readiness check %s failed", name, exc_info=True)
            result = {"status": "fail", "error": type(exc).__name__}
            if critical:
                ready = False
        result["critical"] = critical
        result["ms"] = round((time.monotonic() - started) * 1000, 1)
        checks[name] = result
    return JsonResponse(
        {"status": "ready" if ready else "not_ready", "checks": checks},
        status=200 if ready else 503,
    )
