import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

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
    sam = make_candidate("sam", skills=["AWS"])
    job = make_job(acme, required_skills=["aws"])
    return acme, sam, job


def apply(api_as, candidate, job, file):
    return api_as(candidate.user).post(
        "/api/applications/", {"job": job.id, "cover_letter": "Hi", "resume": file}, format="multipart"
    )


def blob_names(azure_blob):
    return [blob.name for blob in azure_blob.container.list_blobs()]


def http_get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.headers, response.read()  # case-insensitive header lookup
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def test_apply_stores_the_resume_in_blob_storage(api_as, azure_blob, setup):
    _, sam, job = setup
    response = apply(api_as, sam, job, resume("My CV.PDF"))
    body = response.json()

    assert response.status_code == 201
    application = Application.objects.get(id=body["id"])
    key = application.resume.name
    assert application.resume.storage.__class__.__name__ == "AzureStorage"  # type() would say DefaultStorage (LazyObject)
    assert re.fullmatch(rf"resume/job-{job.id}/[0-9a-f]{{32}}\.pdf", key)
    assert blob_names(azure_blob) == [key]
    assert azure_blob.container.download_blob(key).readall() == PDF


def test_rejected_upload_stores_nothing(api_as, azure_blob, setup):
    _, sam, job = setup
    response = apply(api_as, sam, job, resume("cv.txt", b"hello"))

    assert response.status_code == 400
    assert blob_names(azure_blob) == []


def test_stored_resume_is_not_public(api_as, azure_blob, setup):
    _, sam, job = setup
    key = Application.objects.get(id=apply(api_as, sam, job, resume()).json()["id"]).resume.name

    status, headers, _ = http_get(f"{settings.AZURE_BLOB_ENDPOINT}/{azure_blob.name}/{key}")

    assert status == 403
    assert headers["x-ms-error-code"] == "AuthorizationFailure"


def test_sas_link_downloads_the_resume(api_as, azure_blob, setup):
    _, sam, job = setup
    application_id = apply(api_as, sam, job, resume()).json()["id"]
    key = Application.objects.get(id=application_id).resume.name

    link = api_as(sam.user).get(f"/api/applications/{application_id}/resume/").json()
    parsed = urlparse(link["url"])
    query = parse_qs(parsed.query)
    expires = datetime.strptime(query["se"][0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    seconds_left = (expires - datetime.now(timezone.utc)).total_seconds()

    assert parsed.path == f"/{settings.AZURE_ACCOUNT_NAME}/{azure_blob.name}/{key}"
    assert query["sp"] == ["r"]
    assert "sig" in query
    assert settings.RESUME_URL_EXPIRE_SECONDS - 10 <= seconds_left <= settings.RESUME_URL_EXPIRE_SECONDS

    status, headers, content = http_get(link["url"])

    assert status == 200
    assert content == PDF
    assert headers["Content-Disposition"] == f'attachment; filename="resume-{application_id}.pdf"'


def test_tampered_sas_link_is_rejected(api_as, azure_blob, setup):
    _, sam, job = setup
    application_id = apply(api_as, sam, job, resume()).json()["id"]
    url = api_as(sam.user).get(f"/api/applications/{application_id}/resume/").json()["url"]

    tampered = re.sub(r"sig=[^&]+", "sig=AAAA", url)
    status, _, content = http_get(tampered)

    assert status == 403
    assert content != PDF
