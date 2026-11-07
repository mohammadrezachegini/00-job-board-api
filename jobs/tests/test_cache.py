import pytest
from django.core.cache import cache, caches
from redis.exceptions import RedisError

from jobs.cache import JOB_LIST_VERSION_KEY, invalidate_job_list


@pytest.fixture
def board(make_company, make_job):
    acme = make_company("acme")
    make_job(acme, title="Junior DevOps Engineer")
    return acme


def titles(response):
    return [job["title"] for job in response.json()["results"]]


def redis_down(*args, **kwargs):
    raise RedisError("connection refused")


def test_second_request_is_a_hit(api_as, board):
    client = api_as(board.user)

    first = client.get("/api/jobs/")
    second = client.get("/api/jobs/")

    assert (first["X-Cache"], second["X-Cache"]) == ("MISS", "HIT")
    assert first.json() == second.json()


def test_different_queries_are_cached_separately(api_as, board):
    client = api_as(board.user)
    client.get("/api/jobs/")

    assert client.get("/api/jobs/", {"search": "devops"})["X-Cache"] == "MISS"


def test_query_parameter_order_does_not_matter(api_as, board):
    client = api_as(board.user)
    client.get("/api/jobs/?job_type=full_time&location=van")

    assert client.get("/api/jobs/?location=van&job_type=full_time")["X-Cache"] == "HIT"


def test_new_job_invalidates_the_list_only_after_commit(api_as, board, make_job, django_capture_on_commit_callbacks):
    client = api_as(board.user)
    client.get("/api/jobs/")

    with django_capture_on_commit_callbacks() as callbacks:
        make_job(board, title="SRE Intern")

    stale = client.get("/api/jobs/")
    assert stale["X-Cache"] == "HIT"
    assert "SRE Intern" not in titles(stale)

    for callback in callbacks:
        callback()

    fresh = client.get("/api/jobs/")
    assert fresh["X-Cache"] == "MISS"
    assert "SRE Intern" in titles(fresh)


def test_company_change_invalidates_the_list(api_as, board, django_capture_on_commit_callbacks):
    client = api_as(board.user)
    client.get("/api/jobs/")

    with django_capture_on_commit_callbacks(execute=True):
        board.name = "Acme Cloud"
        board.save()

    response = client.get("/api/jobs/")
    assert response["X-Cache"] == "MISS"
    assert response.json()["results"][0]["company"] == "Acme Cloud"


def test_bump_recreates_a_missing_version(db, django_capture_on_commit_callbacks):
    cache.clear()

    with django_capture_on_commit_callbacks(execute=True):
        invalidate_job_list()

    assert cache.get(JOB_LIST_VERSION_KEY) is not None


def test_bump_failure_is_logged_not_raised(db, monkeypatch, caplog, django_capture_on_commit_callbacks):
    monkeypatch.setattr(caches["default"], "incr", redis_down)

    with django_capture_on_commit_callbacks(execute=True):
        invalidate_job_list()

    assert "Could not invalidate the job list cache" in caplog.text


def test_cache_down_falls_back_to_the_database(api_as, board, monkeypatch, caplog):
    monkeypatch.setattr(caches["default"], "get", redis_down)

    response = api_as(board.user).get("/api/jobs/")

    assert response.status_code == 200
    assert "X-Cache" not in response
    assert titles(response) == ["Junior DevOps Engineer"]
    assert "Job list cache unavailable" in caplog.text


def test_cache_write_failure_still_serves_the_list(api_as, board, monkeypatch, caplog):
    monkeypatch.setattr(caches["default"], "set", redis_down)

    response = api_as(board.user).get("/api/jobs/")

    assert response.status_code == 200
    assert response["X-Cache"] == "MISS"
    assert "Could not store job list in cache" in caplog.text