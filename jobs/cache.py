import hashlib
import logging
import time

from django.core.cache import cache
from django.db import transaction
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

JOB_LIST_VERSION_KEY = "jobs:list:version"


def _current_version():
    version = cache.get(JOB_LIST_VERSION_KEY)
    if version is None:
        cache.add(JOB_LIST_VERSION_KEY, int(time.time()), timeout=None)
        version = cache.get(JOB_LIST_VERSION_KEY)
    return version


def job_list_cache_key(request):
    params = sorted(request.query_params.lists())
    raw = f"{request.get_host()}|{params}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"jobs:list:v{_current_version()}:{digest}"


def invalidate_job_list():
    def bump():
        try:
            cache.incr(JOB_LIST_VERSION_KEY)
        except ValueError:
            cache.add(JOB_LIST_VERSION_KEY, int(time.time()), timeout=None)
        except RedisError:
            logger.warning("Could not invalidate the job list cache", exc_info=True)

    transaction.on_commit(bump)