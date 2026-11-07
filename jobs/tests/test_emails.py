import pytest
from django.conf import settings

from jobs.emails import send_status_changed_email


@pytest.fixture
def application(make_company, make_candidate, make_job, make_application):
    def _make(title="Junior DevOps Engineer", first_name=""):
        sam = make_candidate("sam")
        if first_name:
            sam.user.first_name = first_name
            sam.user.save()
        job = make_job(make_company("acme", name="Acme"), title=title)
        return make_application(job, sam)

    return _make


def test_status_email_content(application, mailoutbox):
    send_status_changed_email(application(), "interview")
    [email] = mailoutbox

    assert email.subject == "Your application for Junior DevOps Engineer: Interview"
    assert email.to == ["sam@example.test"]
    assert email.from_email == settings.DEFAULT_FROM_EMAIL
    assert "Hi sam," in email.body
    assert "Junior DevOps Engineer at Acme" in email.body
    assert "New status: Interview" in email.body


def test_first_name_is_used_when_set(application, mailoutbox):
    send_status_changed_email(application(first_name="Sam"), "interview")

    assert "Hi Sam," in mailoutbox[0].body


def test_plain_text_is_not_html_escaped(application, mailoutbox):
    send_status_changed_email(application(title="R&D <Lead>"), "offered")
    [email] = mailoutbox

    assert "R&D <Lead> at Acme" in email.body
    assert email.subject == "Your application for R&D <Lead>: Offered"


def test_newlines_cannot_reach_the_subject(application, mailoutbox):
    send_status_changed_email(application(title="Line one\nBcc: attacker@evil.test"), "offered")
    [email] = mailoutbox

    assert "\n" not in email.subject
    assert email.subject == "Your application for Line one Bcc: attacker@evil.test: Offered"
    assert email.bcc == []


def test_unknown_status_raises(application):
    with pytest.raises(ValueError):
        send_status_changed_email(application(), "hired")