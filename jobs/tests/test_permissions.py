from types import SimpleNamespace

import pytest
from django.contrib.auth.models import AnonymousUser
from rest_framework.test import APIClient

from jobs.models import Application, User
from jobs.permissions import IsApplicantOwner, IsCandidate, IsJobOwner, IsVerifiedCompany


def req(user):
    return SimpleNamespace(user=user)


# ---------- the classes on their own ----------


def test_is_verified_company(make_company, make_candidate):
    permission = IsVerifiedCompany()

    assert not permission.has_permission(req(AnonymousUser()), None)
    assert not permission.has_permission(req(make_candidate().user), None)
    assert permission.message == "Only company accounts can do this."
    assert permission.has_permission(req(make_company("acme").user), None)


def test_unverified_or_missing_company_gets_the_unverified_message(make_company, db):
    permission = IsVerifiedCompany()
    assert not permission.has_permission(req(make_company("initech", verified=False).user), None)
    assert permission.message == "Your company account is not verified."

    orphan = User.objects.create_user(
        username="orphan", email="orphan@example.test", password="x", role=User.Role.COMPANY
    )
    permission = IsVerifiedCompany()
    assert not permission.has_permission(req(orphan), None)
    assert permission.message == "Your company account is not verified."

    assert IsVerifiedCompany.message == "Only company accounts can do this."


def test_is_candidate(make_company, make_candidate, db):
    permission = IsCandidate()
    no_profile = User.objects.create_user(
        username="ghost", email="ghost@example.test", password="x", role=User.Role.CANDIDATE
    )

    assert not permission.has_permission(req(AnonymousUser()), None)
    assert not permission.has_permission(req(make_company().user), None)
    assert not permission.has_permission(req(no_profile), None)
    assert permission.has_permission(req(make_candidate().user), None)


def test_is_job_owner(make_company, make_candidate, make_job, make_application):
    acme, globex = make_company("acme"), make_company("globex")
    sam = make_candidate()
    job = make_job(acme)
    application = make_application(job, sam)
    permission = IsJobOwner()

    assert permission.has_object_permission(req(acme.user), None, job)
    assert permission.has_object_permission(req(acme.user), None, application)
    assert not permission.has_object_permission(req(globex.user), None, job)
    assert not permission.has_object_permission(req(globex.user), None, application)
    assert not permission.has_object_permission(req(sam.user), None, job)
    assert not permission.has_object_permission(req(AnonymousUser()), None, job)


def test_is_applicant_owner(make_company, make_candidate, make_job, make_application):
    acme, globex = make_company("acme"), make_company("globex")
    sam, riya = make_candidate("sam"), make_candidate("riya")
    application = make_application(make_job(acme), sam)
    permission = IsApplicantOwner()

    assert permission.has_object_permission(req(sam.user), None, application)
    assert permission.has_object_permission(req(acme.user), None, application)
    assert not permission.has_object_permission(req(riya.user), None, application)
    assert not permission.has_object_permission(req(globex.user), None, application)
    assert not permission.has_object_permission(req(AnonymousUser()), None, application)


# ---------- the matrix through the real endpoints ----------


@pytest.fixture
def world(make_company, make_candidate, make_job, make_application):
    acme = make_company("acme", verified=True)
    globex = make_company("globex", verified=True)
    initech = make_company("initech", verified=False)
    sam = make_candidate("sam", skills=["aws"])
    riya = make_candidate("riya")
    job = make_job(acme, required_skills=["aws"])
    application = make_application(job, sam, resume="resume/job-test/cv.pdf")
    users = {
        "anon": None,
        "acme": acme.user,
        "globex": globex.user,
        "initech": initech.user,
        "sam": sam.user,
        "riya": riya.user,
    }
    return SimpleNamespace(job=job, application=application, users=users)


@pytest.fixture
def client_for(world):
    def _client(who):
        client = APIClient()
        if world.users[who] is not None:
            client.force_authenticate(user=world.users[who])
        return client

    return _client


NEW_JOB = {
    "title": "SRE Intern",
    "description": "Keep it running.",
    "location": "Remote",
    "required_skills": ["Python"],
}


@pytest.mark.parametrize(
    ("who", "expected"),
    [("anon", 401), ("sam", 200), ("riya", 200), ("acme", 200), ("initech", 200)],
)
def test_job_list_and_detail_need_a_login_only(client_for, world, who, expected):
    client = client_for(who)

    assert client.get("/api/jobs/").status_code == expected
    assert client.get(f"/api/jobs/{world.job.id}/").status_code == expected


@pytest.mark.parametrize(
    ("who", "expected"),
    [("anon", 401), ("sam", 403), ("initech", 403), ("acme", 201), ("globex", 201)],
)
def test_only_verified_companies_post_jobs(client_for, who, expected):
    response = client_for(who).post("/api/jobs/", NEW_JOB, format="json")

    assert response.status_code == expected


def test_job_post_denials_explain_why(client_for):
    unverified = client_for("initech").post("/api/jobs/", NEW_JOB, format="json")
    candidate = client_for("sam").post("/api/jobs/", NEW_JOB, format="json")

    assert unverified.json()["detail"] == "Your company account is not verified."
    assert candidate.json()["detail"] == "Only company accounts can do this."


@pytest.mark.parametrize(
    ("who", "expected"),
    [("anon", 401), ("sam", 403), ("globex", 403), ("acme", 200)],
)
def test_only_the_owner_updates_a_job(client_for, world, who, expected):
    response = client_for(who).patch(
        f"/api/jobs/{world.job.id}/", {"title": "Changed"}, format="json"
    )
    world.job.refresh_from_db()

    assert response.status_code == expected
    assert (world.job.title == "Changed") == (expected == 200)


@pytest.mark.parametrize(
    ("who", "expected"),
    [("anon", 401), ("sam", 403), ("globex", 403), ("acme", 200)],
)
def test_only_the_owner_sees_applicants(client_for, world, who, expected):
    response = client_for(who).get(f"/api/jobs/{world.job.id}/applications/")

    assert response.status_code == expected


@pytest.mark.parametrize(
    ("who", "expected"),
    [("anon", 401), ("acme", 403), ("sam", 400)],
)
def test_only_candidates_apply(client_for, who, expected):
    response = client_for(who).post("/api/applications/", {}, format="multipart")

    assert response.status_code == expected


@pytest.mark.parametrize(
    ("who", "expected"),
    [("anon", 401), ("riya", 403), ("globex", 403), ("sam", 200), ("acme", 200)],
)
def test_application_detail_for_applicant_and_job_owner_only(client_for, world, who, expected):
    response = client_for(who).get(f"/api/applications/{world.application.id}/")

    assert response.status_code == expected


@pytest.mark.parametrize(
    ("who", "expected"),
    [("anon", 401), ("sam", 403), ("riya", 403), ("globex", 403), ("acme", 200)],
)
def test_only_the_job_owner_changes_status(client_for, world, who, expected):
    response = client_for(who).patch(
        f"/api/applications/{world.application.id}/status/",
        {"status": "reviewing"},
        format="json",
    )
    world.application.refresh_from_db()

    assert response.status_code == expected
    expected_status = "reviewing" if expected == 200 else Application.Status.SUBMITTED
    assert world.application.status == expected_status


@pytest.mark.parametrize(
    ("who", "expected"),
    [("anon", 401), ("riya", 403), ("globex", 403), ("sam", 200), ("acme", 200)],
)
def test_resume_link_for_applicant_and_job_owner_only(client_for, world, who, expected):
    response = client_for(who).get(f"/api/applications/{world.application.id}/resume/")

    assert response.status_code == expected