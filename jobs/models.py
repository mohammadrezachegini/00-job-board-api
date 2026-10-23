from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models


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
