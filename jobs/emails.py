from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from .models import Application


def _one_line(text):
    return " ".join(text.split())

def send_status_changed_email(application, new_status):
    candidate = application.candidate.user
    status_label = Application.Status(new_status).label
    context = {
        "name": candidate.first_name or candidate.username,
        "job_title": application.job.title,
        "company": application.job.company.name,
        "status": status_label,
    }
    
    subject = _one_line(f"Your application for {application.job.title}: {status_label}")
    body = render_to_string("emails/status_changed.txt", context)
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [candidate.email], fail_silently=False)