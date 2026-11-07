import re
from urllib.parse import parse_qs, urlparse

import pytest
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from jobs.models import Application
from jobs.serializers import ApplicationSerializer

PDF = b"%PDF-1.4\nfake resume\n%%EOF\n"


def resume(name="cv.pdf", content=PDF):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


@pytest.fixture
def setup(make_company, make_candidate, make_job):
    acme = make_company("acme")
    sam = make_candidate("sam")
    job = make_job(acme)
    return acme, sam, job


def apply(api_as, candidate, job, file):
    return api_as(candidate.user).post(
        "/api/applications/", {"job": job.id, "cover_letter": "Hi", "resume": file}, format="multipart"
    )


def bucket_keys(aws):
    response = aws.s3.list_objects_v2(Bucket=aws.bucket)
    return [obj["Key"] for obj in response.get("Contents", [])]


def test_apply_stores_the_resume_in_s3(api_as, aws, setup):
    _, sam, job = setup
    response = apply(api_as, sam, job, resume("My CV.PDF"))
    body = response.json()

    assert response.status_code == 201
    assert body["has_resume"] is True
    assert "resume" not in body
    key = Application.objects.get(id=body["id"]).resume.name
    assert re.fullmatch(rf"resume/job-{job.id}/[0-9a-f]{{32}}\.pdf", key)
    assert bucket_keys(aws) == [key]
    assert aws.s3.get_object(Bucket=aws.bucket, Key=key)["Body"].read() == PDF


def test_stored_resume_is_private(api_as, aws, setup):
    _, sam, job = setup
    application_id = apply(api_as, sam, job, resume()).json()["id"]
    key = Application.objects.get(id=application_id).resume.name

    grants = aws.s3.get_object_acl(Bucket=aws.bucket, Key=key)["Grants"]

    assert [grant["Permission"] for grant in grants] == ["FULL_CONTROL"]
    assert all("URI" not in grant["Grantee"] for grant in grants)


def test_rejected_upload_stores_nothing(api_as, aws, setup):
    _, sam, job = setup
    response = apply(api_as, sam, job, resume("cv.txt", b"hello"))

    assert response.status_code == 400
    assert bucket_keys(aws) == []


def test_duplicate_race_returns_400_but_leaves_the_file_behind(api_as, aws, setup, make_application, monkeypatch):
    _, sam, job = setup
    make_application(job, sam)
    monkeypatch.setattr(ApplicationSerializer, "validate", lambda self, attrs: attrs)

    response = apply(api_as, sam, job, resume())

    assert response.status_code == 400
    assert response.json() == {"job": "You have already applied for this job."}
    assert Application.objects.count() == 1
    assert len(bucket_keys(aws)) == 1


def test_presigned_link_is_signed_for_the_stored_file(api_as, aws, setup):
    _, sam, job = setup
    application_id = apply(api_as, sam, job, resume()).json()["id"]
    key = Application.objects.get(id=application_id).resume.name

    url = api_as(sam.user).get(f"/api/applications/{application_id}/resume/").json()["url"]
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.path.endswith(key)
    assert query["X-Amz-Expires"] == [str(settings.RESUME_URL_EXPIRE_SECONDS)]
    assert "X-Amz-Signature" in query
    assert query["response-content-disposition"] == [f'attachment; filename="resume-{application_id}.pdf"']