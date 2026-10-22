from django.contrib.auth.models import AbstractUser
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
    
        