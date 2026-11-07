import pytest

from jobs.models import Application, CandidateProfile, Company, Job, User

PASSWORD = "test-pass-123"


@pytest.fixture
def make_company(db):
    def _make(username="acme", verified=True, name=None):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.test",
            password=PASSWORD,
            role=User.Role.COMPANY,
        )
        return Company.objects.create(
            user=user, name=name or username.title(), is_verified=verified
        )

    return _make


@pytest.fixture
def make_candidate(db):
    def _make(username="sam", skills=None):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.test",
            password=PASSWORD,
            role=User.Role.CANDIDATE,
        )
        return CandidateProfile.objects.create(user=user, skills=skills or [])

    return _make


@pytest.fixture
def make_job(db):
    def _make(company, title="Junior DevOps Engineer", required_skills=None, location="Vancouver", **fields):
        return Job.objects.create(
            company=company,
            title=title,
            description="Build and run things.",
            location=location,
            required_skills=required_skills or [],
            **fields,
        )

    return _make

@pytest.fixture
def make_application(db):
    def _make(job, candidate, **fields):
        return Application.objects.create(job=job, candidate=candidate, **fields)

    return _make


@pytest.fixture(autouse=True)
def local_cache(settings):
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    }
    from django.core.cache import cache

    cache.clear()


@pytest.fixture(autouse=True)
def fast_password_hashing(settings):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def api_as():
    from rest_framework.test import APIClient

    def _client(user=None):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user=user)
        return client

    return _client
