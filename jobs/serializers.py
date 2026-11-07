from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db import transaction
from rest_framework import serializers

from .models import CandidateProfile, Company, Job, Application
from . import matching

User = get_user_model()


class RegisteredUserSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    role = serializers.ChoiceField(choices=User.Role.choices, read_only=True)


class ResumeLinkSerializer(serializers.Serializer):
    url = serializers.URLField(read_only=True)
    expires_in = serializers.IntegerField(read_only=True, help_text="Seconds until the link stops working.")

class BaseRegistrationSerializer(serializers.Serializer):
    username = serializers.CharField(
        max_length=150, validators=[UnicodeUsernameValidator()]
    )
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "An account with this email already exists."
            )
        return value

    def validate_password(self, value):
        password_validation.validate_password(value)
        return value

    def create_user(self, validated_data, role):
        return User.objects.create_user(
            username=validated_data.pop("username"),
            email=validated_data.pop("email"),
            password=validated_data.pop("password"),
            role=role,
        )

    def to_representation(self, user):
        return RegisteredUserSerializer(user).data


class CompanyRegistrationSerializer(BaseRegistrationSerializer):
    company_name = serializers.CharField(max_length=200)
    website = serializers.URLField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)

    @transaction.atomic
    def create(self, validated_data):
        user = self.create_user(validated_data, role=User.Role.COMPANY)
        Company.objects.create(
            user=user, name=validated_data.pop("company_name"), **validated_data
        )
        return user


class CandidateRegistrationSerializer(BaseRegistrationSerializer):
    headline = serializers.CharField(max_length=200, required=False, allow_blank=True)
    location = serializers.CharField(max_length=200, required=False, allow_blank=True)
    skills = serializers.ListField(
        child=serializers.CharField(max_length=100), required=False
    )

    @transaction.atomic
    def create(self, validated_data):
        user = self.create_user(validated_data, role=User.Role.CANDIDATE)
        CandidateProfile.objects.create(user=user, **validated_data)
        return user


class JobSerializer(serializers.ModelSerializer):
    company = serializers.CharField(source="company.name", read_only=True)

    class Meta:
        model = Job
        fields = [
            "id",
            "company",
            "title",
            "description",
            "location",
            "job_type",
            "required_skills",
            "is_open",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
    
    def validate_required_skills(self, value):
        return list(dict.fromkeys([skill.strip().lower() for skill in value if skill.strip()]))


class ApplicationSerializer(serializers.ModelSerializer):
    job = serializers.PrimaryKeyRelatedField(queryset=Job.objects.all())
    job_title = serializers.CharField(source="job.title", read_only=True)
    candidate = serializers.CharField(source="candidate.user.username", read_only=True)
    match_score = serializers.SerializerMethodField()
    has_resume = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = [
            "id",
            "job",
            "job_title",
            "candidate",
            "cover_letter",
            "resume",
            "has_resume",
            "status",
            "match_score",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "status", "created_at", "updated_at"]
        validators = []
        extra_kwargs = {"resume": {"required": True, "write_only": True}}

    def get_has_resume(self, obj) -> bool:
        return bool(obj.resume)

    def get_match_score(self, obj) -> int | None:
        return matching.match_score(obj.job.required_skills, obj.candidate.skills)

    def validate_job(self, job):
        if not job.is_open:
            raise serializers.ValidationError(
                "This job is no longer accepting applications."
            )
        return job

    def validate(self, attrs):
        profile = getattr(self.context["request"].user, "candidate_profile", None)
        if (
            profile
            and Application.objects.filter(job=attrs["job"], candidate=profile).exists()
        ):
            raise serializers.ValidationError(
                {"job": "You have already applied for this job."}
            )
        return attrs


class ApplicationStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Application
        fields = ["status"]
        extra_kwargs = {"status": {"required": True}}
