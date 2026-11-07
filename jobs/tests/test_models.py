import re

import pytest
from django.db import IntegrityError, transaction

from jobs.models import Application, Company, Job, ProcessedEvent, User, resume_upload_path


def test_role_properties(make_company, make_candidate):
    company_user = make_company().user
    candidate_user = make_candidate().user

    assert company_user.is_company and not company_user.is_candidate
    assert candidate_user.is_candidate and not candidate_user.is_company


def test_email_must_be_unique(make_candidate):
    make_candidate(username="sam")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(username="sam2", email="sam@example.test", password="x")


def test_job_defaults(make_company, make_job):
    job = make_job(make_company())

    assert job.is_open is True
    assert job.job_type == Job.JobType.FULL_TIME
    assert job.required_skills == []


def test_application_defaults_to_submitted(make_company, make_candidate, make_job, make_application):
    application = make_application(make_job(make_company()), make_candidate())

    assert application.status == Application.Status.SUBMITTED


def test_one_application_per_job_per_candidate(make_company, make_candidate, make_job, make_application):
    company = make_company()
    job, other_job = make_job(company), make_job(company, title="SRE Intern")
    sam = make_candidate()
    make_application(job, sam)

    with pytest.raises(IntegrityError), transaction.atomic():
        make_application(job, sam)

    make_application(other_job, sam)          # same candidate, different job: allowed
    assert Application.objects.filter(candidate=sam).count() == 2


def test_event_id_must_be_unique(db):
    ProcessedEvent.objects.create(event_id="abc", event_type="application.status_changed")
    with pytest.raises(IntegrityError), transaction.atomic():
        ProcessedEvent.objects.create(event_id="abc", event_type="application.status_changed")


def test_ordering(make_company, make_job):
    zeta, acme = make_company(username="zeta"), make_company(username="acme")
    first = make_job(acme, title="First")
    second = make_job(acme, title="Second")

    assert list(Company.objects.all()) == [acme, zeta]       # by name
    assert list(Job.objects.all()) == [second, first]         # newest first


def test_str_methods(make_company, make_candidate, make_job, make_application):
    company = make_company(name="Acme")
    sam = make_candidate(username="sam")
    job = make_job(company, title="Junior DevOps Engineer")
    application = make_application(job, sam)
    event = ProcessedEvent.objects.create(event_id="e-1", event_type="application.status_changed")

    assert str(company) == "Acme"
    assert str(sam) == "sam"
    assert str(job) == "Junior DevOps Engineer (Acme)"
    assert str(application) == "sam -> Junior DevOps Engineer (Acme)"
    assert str(event) == "application.status_changed e-1"


def test_resume_upload_path_is_random_and_keeps_a_lowercase_extension():
    application = Application(job_id=7)

    first = resume_upload_path(application, "My CV.PDF")
    second = resume_upload_path(application, "My CV.PDF")

    assert re.fullmatch(r"resume/job-7/[0-9a-f]{32}\.pdf", first)
    assert first != second
    assert "My CV" not in first


def test_deleting_a_company_user_cascades(make_company, make_candidate, make_job, make_application):
    company = make_company()
    make_application(make_job(company), make_candidate())

    company.user.delete()

    assert Company.objects.count() == 0
    assert Job.objects.count() == 0
    assert Application.objects.count() == 0