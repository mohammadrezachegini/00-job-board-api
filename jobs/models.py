import uuid
from pathlib import Path
from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from .validators import validate_resume


class User(AbstractUser):
    class Role(models.TextChoices):
        COMPANY = "company", "Company"
        CANDIDATE = "candidate", "Candidate"

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, choices=Role.choices)

    @property
    def is_company(self):
        return self.role == self.Role.COMPANY

    @property
    def is_candidate(self):
        return self.role == self.Role.CANDIDATE


class Company(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="company",
    )
    name = models.CharField(max_length=255)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "companies"
        ordering = ["name"]

    def __str__(self):
        return self.name


class CandidateProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="candidate_profile",
    )
    headline = models.CharField(max_length=200, blank=True)
    location = models.CharField(max_length=100, blank=True)
    skills = ArrayField(models.CharField(max_length=50), default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.username


class Job(models.Model):

    class JobType(models.TextChoices):
        FULL_TIME = "full_time", "Full-time"
        PART_TIME = "part_time", "Part-time"
        CONTRACT = "contract", "Contract"
        INTERNSHIP = "internship", "Internship"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="jobs")
    title = models.CharField(max_length=200)
    description = models.TextField()
    location = models.CharField(max_length=100)
    job_type = models.CharField(
        max_length=20, choices=JobType.choices, default=JobType.FULL_TIME
    )
    required_skills = ArrayField(
        models.CharField(max_length=50), default=list, blank=True
    )
    is_open = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.company})"


def resume_upload_path(instance, filename):
    extentsion = Path(filename).suffix.lower()
    return f"resume/job-{instance.job_id}/{uuid.uuid4().hex}{extentsion}"


class Application(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        REVIEWING = "reviewing", "Reviewing"
        INTERVIEW = "interview", "Interview"
        OFFERED = "offered", "Offered"
        REJECTED = "rejected", "Rejected"

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="applications")
    candidate = models.ForeignKey(
        CandidateProfile, on_delete=models.CASCADE, related_name="applications"
    )
    cover_letter = models.TextField(blank=True)
    resume = models.FileField(upload_to=resume_upload_path, validators=[validate_resume], blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SUBMITTED
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["job", "candidate"], name="unique_application_per_job"
            ),
        ]

    def __str__(self):
        return f"{self.candidate} -> {self.job}"
