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
    def _make(company, title="Junior DevOps Engineer", required_skills=None, **fields):
        return Job.objects.create(
            company=company,
            title=title,
            description="Build and run things.",
            location="Vancouver",
            required_skills=required_skills or [],
            **fields,
        )

    return _make


@pytest.fixture
def make_application(db):
    def _make(job, candidate, **fields):
        return Application.objects.create(job=job, candidate=candidate, **fields)

    return _make