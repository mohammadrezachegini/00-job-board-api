import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from jobs.models import Application

PDF = b"%PDF-1.4\nfake resume\n%%EOF\n"


def resume(name="cv.pdf", content=PDF):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


@pytest.fixture
def setup(make_company, make_candidate, make_job):
    acme = make_company("acme")
    sam = make_candidate("sam", skills=["AWS", "Docker"])
    job = make_job(acme, required_skills=["aws", "terraform"])
    return acme, sam, job


# ---------- applying: everything rejected before any upload ----------


def test_resume_is_required(api_as, setup):
    _, sam, job = setup
    response = api_as(sam.user).post("/api/applications/", {"job": job.id}, format="multipart")

    assert response.status_code == 400
    assert "resume" in response.json()


def test_wrong_resume_type_is_rejected(api_as, setup):
    _, sam, job = setup
    response = api_as(sam.user).post(
        "/api/applications/", {"job": job.id, "resume": resume("cv.txt", b"hello")}, format="multipart"
    )

    assert response.status_code == 400
    assert "resume" in response.json()


def test_closed_job_is_rejected(api_as, setup, make_job):
    acme, sam, _ = setup
    closed = make_job(acme, title="Closed", is_open=False)
    response = api_as(sam.user).post("/api/applications/", {"job": closed.id, "resume": resume()}, format="multipart")

    assert response.status_code == 400
    assert response.json()["job"] == ["This job is no longer accepting applications."]


def test_unknown_job_is_rejected(api_as, setup):
    _, sam, _ = setup
    response = api_as(sam.user).post("/api/applications/", {"job": 999999, "resume": resume()}, format="multipart")

    assert response.status_code == 400
    assert "job" in response.json()


def test_second_application_is_rejected(api_as, setup, make_application):
    _, sam, job = setup
    make_application(job, sam)
    response = api_as(sam.user).post("/api/applications/", {"job": job.id, "resume": resume()}, format="multipart")

    assert response.status_code == 400
    assert response.json()["job"] == ["You have already applied for this job."]
    assert Application.objects.count() == 1


# ---------- reading ----------


def test_detail_shape_hides_the_resume_path(api_as, setup, make_application):
    _, sam, job = setup
    application = make_application(job, sam, resume="resume/job-1/abc.pdf", cover_letter="Hi")
    body = api_as(sam.user).get(f"/api/applications/{application.id}/").json()

    assert body["match_score"] == 50
    assert body["has_resume"] is True
    assert "resume" not in body
    assert body["job_title"] == job.title
    assert body["candidate"] == "sam"
    assert body["status"] == "submitted"


def test_applicants_list_has_match_scores(api_as, setup, make_application):
    acme, sam, job = setup
    make_application(job, sam)
    results = api_as(acme.user).get(f"/api/jobs/{job.id}/applications/").json()["results"]

    assert [(a["candidate"], a["match_score"]) for a in results] == [("sam", 50)]


def test_missing_application_is_404(api_as, setup):
    _, sam, _ = setup

    assert api_as(sam.user).get("/api/applications/999999/").status_code == 404


def test_resume_link_uses_the_public_endpoint(api_as, setup, make_application):
    _, sam, job = setup
    application = make_application(job, sam, resume="resume/job-1/abc.pdf")
    body = api_as(sam.user).get(f"/api/applications/{application.id}/resume/").json()

    assert body["expires_in"] == settings.RESUME_URL_EXPIRE_SECONDS
    assert body["url"].startswith(settings.AWS_S3_PUBLIC_ENDPOINT_URL)
    assert "resume/job-1/abc.pdf" in body["url"]
    assert "Signature" in body["url"]


def test_no_resume_is_404(api_as, setup, make_application):
    acme, sam, job = setup
    application = make_application(job, sam)
    response = api_as(acme.user).get(f"/api/applications/{application.id}/resume/")

    assert response.status_code == 404
    assert response.json()["detail"] == "This application has no resume."


# ---------- status ----------


@pytest.mark.parametrize(
    ("data", "message"),
    [({}, "This field is required."), ({"status": "hired"}, '"hired" is not a valid choice.')],
)
def test_bad_status_bodies_are_rejected(api_as, setup, make_application, data, message):
    acme, sam, job = setup
    application = make_application(job, sam)
    response = api_as(acme.user).patch(f"/api/applications/{application.id}/status/", data, format="json")

    assert response.status_code == 400
    assert response.json()["status"] == [message]


def test_status_change_publishes_once_and_only_on_change(api_as, setup, make_application, monkeypatch):
    acme, sam, job = setup
    application = make_application(job, sam)
    calls = []
    monkeypatch.setattr("jobs.views.publish_status_changed", lambda app, old: calls.append((app.id, old)))
    client = api_as(acme.user)
    url = f"/api/applications/{application.id}/status/"

    first = client.patch(url, {"status": "reviewing"}, format="json")
    second = client.patch(url, {"status": "reviewing"}, format="json")

    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == "reviewing"
    assert "match_score" in first.json()
    assert calls == [(application.id, "submitted")]