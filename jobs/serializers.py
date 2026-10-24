from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.db import transaction
from rest_framework import serializers

from .models import CandidateProfile, Company, Job

User = get_user_model()


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

    def validate_email(delf, value):
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
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role,
        }


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
    skills = serializers.ListField(child=serializers.CharField(max_length=100), required=False)
    
    @transaction.atomic
    def create(self, validated_data):
        user = self.create_user(validated_data, role=User.Role.CANDIDATE)
        CandidateProfile.objects.create(user=user, **validated_data)
        return user
    

