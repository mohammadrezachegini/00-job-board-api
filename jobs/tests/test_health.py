from botocore.exceptions import EndpointConnectionError
from django.core.cache import caches
from django.db import OperationalError
from redis.exceptions import RedisError

import pytest

from cloud import health


def failing(error):
    def check():
        raise error

    return check


def ok():
    return None


def use_checks(monkeypatch, **replacements):
    checks = [(name, replacements.get(name, check), critical) for name, check, critical in health.CHECKS]
    monkeypatch.setattr(health, "CHECKS", checks)


def statuses(body):
    return {name: result["status"] for name, result in body["checks"].items()}


def test_all_ok_with_real_checks(client, db, aws):
    response = client.get("/readyz")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "ready"
    assert statuses(body) == {"database": "ok", "cache": "ok", "queue": "ok"}
    assert {name: r["critical"] for name, r in body["checks"].items()} == {"database": True, "cache": False, "queue": False}
    assert all(isinstance(r["ms"], float) for r in body["checks"].values())
    assert "no-cache" in response["Cache-Control"]


def test_database_down_is_503_and_hides_the_message(client, monkeypatch, caplog):
    use_checks(monkeypatch, database=failing(OperationalError("connect failed: password=hunter2")), queue=ok)

    response = client.get("/readyz")
    body = response.json()

    assert response.status_code == 503
    assert body["status"] == "not_ready"
    assert body["checks"]["database"]["status"] == "fail"
    assert body["checks"]["database"]["error"] == "OperationalError"
    assert "hunter2" not in response.content.decode()
    assert "Readiness check database failed" in caplog.text


@pytest.mark.parametrize(
    ("name", "error", "expected_error"),
    [
        ("cache", RedisError("down"), "RedisError"),
        ("queue", EndpointConnectionError(endpoint_url="http://sqs.invalid"), "EndpointConnectionError"),
    ],
)
def test_non_critical_failure_stays_ready(client, db, monkeypatch, name, error, expected_error):
    replacements = {"queue": ok, name: failing(error)}
    use_checks(monkeypatch, **replacements)

    response = client.get("/readyz")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "ready"
    assert body["checks"][name] == {**body["checks"][name], "status": "fail", "error": expected_error}


def test_liveness_ignores_every_dependency(client, monkeypatch):
    use_checks(monkeypatch, database=failing(OperationalError()), cache=failing(RedisError()), queue=failing(RuntimeError()))

    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 503


def test_cache_check_detects_a_bad_read_back(monkeypatch):
    monkeypatch.setattr(caches["default"], "get", lambda key: "something else")

    with pytest.raises(RuntimeError, match="read-back mismatch"):
        health._check_cache()


def test_queue_check_pings_the_queue(aws):
    assert health._check_queue() is None