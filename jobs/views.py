from django.db import IntegrityError, transaction
from django.conf import settings
from rest_framework import generics, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import NotFound
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter
from .permissions import IsVerifiedCompany, IsCandidate, IsJobOwner, IsApplicantOwner
from .storage import resume_download_url
from .models import Application, Job
from .filters import JobFilter
from .events import publish_status_changed
from drf_spectacular.utils import OpenApiResponse, extend_schema

import logging

from django.core.cache import cache
from redis.exceptions import RedisError

from .cache import job_list_cache_key

from .serializers import (
    ApplicationSerializer,
    ApplicationStatusSerializer,
    CandidateRegistrationSerializer,
    CompanyRegistrationSerializer,
    JobSerializer,
    RegisteredUserSerializer,
    ResumeLinkSerializer,
)

logger = logging.getLogger(__name__)

@extend_schema(responses={201: RegisteredUserSerializer})
class CompanyRegisterView(generics.CreateAPIView):
    serializer_class = CompanyRegistrationSerializer
    permission_classes = [AllowAny]
    authentication_classes = []

@extend_schema(responses={201: RegisteredUserSerializer})
class CandidateRegisterView(generics.CreateAPIView):
    serializer_class = CandidateRegistrationSerializer
    permission_classes = [AllowAny]
    authentication_classes = []


class JobViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):

    serializer_class = JobSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter, SearchFilter]
    filterset_class = JobFilter
    search_fields = ["title", "description", "company__name"]
    ordering_fields = ["created_at", "title"]
    ordering = ["-created_at"]

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsVerifiedCompany()]
        if self.action in ("update", "partial_update", "applications"):
            return [IsAuthenticated(), IsJobOwner()]
        return super().get_permissions()

    def get_queryset(self):
        queryset = Job.objects.select_related("company")
        if self.action == "list":
            queryset = queryset.filter(is_open=True)
        return queryset

    def perform_create(self, serializer):
        serializer.save(company=self.request.user.company)
        
    @extend_schema(responses=ApplicationSerializer(many=True))
    @action(detail=True, methods=["get"])
    def applications(self, request, pk=None):
        job = self.get_object()
        queryset = job.applications.select_related("job__company", "candidate__user")
        page = self.paginate_queryset(queryset)
        serializer = ApplicationSerializer(
            page, many=True, context=self.get_serializer_context()
        )
        return self.get_paginated_response(serializer.data)

    def list(self, request, *args, **kwargs):
        try:
            key = job_list_cache_key(request)
            cached = cache.get(key)
        except RedisError:
            logger.warning("Job list cache unavailable", exc_info=True)
            return super().list(request, *args, **kwargs)

        if cached is not None:
            response = Response(cached)
            response["X-Cache"] = "HIT"
            return response

        response = super().list(request, *args, **kwargs)
        if response.status_code == 200:
            try:
                cache.set(key, response.data, timeout=settings.JOB_LIST_CACHE_SECONDS)
            except RedisError:
                logger.warning("Could not store job list in cache", exc_info=True)
        response["X-Cache"] = "MISS"
        return response


class ApplicationViewSet(
    mixins.CreateModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = ApplicationSerializer
    queryset = Application.objects.select_related("job__company", "candidate__user")

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsCandidate()]
        if self.action in ("retrieve", "resume"):
            return [IsAuthenticated(), IsApplicantOwner()]
        if self.action == "set_status":
            return [IsAuthenticated(), IsJobOwner()]
        return super().get_permissions()

    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                serializer.save(candidate=self.request.user.candidate_profile)
        except IntegrityError:
            raise ValidationError({"job": "You have already applied for this job."})

    @extend_schema(request=ApplicationStatusSerializer, responses=ApplicationSerializer)
    @action(detail=True, methods=["patch"], url_path="status")
    def set_status(self, request, pk=None):
        application = self.get_object()
        old_status = application.status
        serializer = ApplicationStatusSerializer(application, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        if application.status != old_status:
            publish_status_changed(application, old_status)
        return Response(
            ApplicationSerializer(
                application, context=self.get_serializer_context()
            ).data
        )

    @extend_schema(
        responses={
            200: ResumeLinkSerializer,
            404: OpenApiResponse(description="This application has no resume."),
        }
    )
    @action(detail=True, methods=["get"])
    @action(detail=True, methods=["get"])
    def resume(self, request, pk=None):
        application = self.get_object()
        if not application.resume:
            raise NotFound("This application has no resume.")
        return Response(
            ResumeLinkSerializer(
                {
                    "url": resume_download_url(application),
                    "expires_in": settings.RESUME_URL_EXPIRE_SECONDS,
                }
            ).data
        )
