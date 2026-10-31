from django.db import IntegrityError, transaction
from django.conf import settings
from rest_framework import generics, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import NotFound
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter
from .permissions import IsVerifiedCompany, IsCandidate, IsJobOwner, IsApplicantOwner
from .storage import resume_download_url
from .models import Application, Job
from .filters import JobFilter
from .serializers import (
    ApplicationSerializer,
    ApplicationStatusSerializer,
    CandidateRegistrationSerializer,
    CompanyRegistrationSerializer,
    JobSerializer,
)


class CompanyRegisterView(generics.CreateAPIView):
    serializer_class = CompanyRegistrationSerializer
    permission_classes = [AllowAny]
    authentication_classes = []


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
        if not self.request.user.is_company:
            raise PermissionDenied("Only company users can create jobs.")
        serializer.save(company=self.request.user.company)

    @action(detail=True, methods=["get"])
    def applications(self, request, pk=None):
        job = self.get_object()
        queryset = job.applications.select_related("job__company", "candidate__user")
        page = self.paginate_queryset(queryset)
        serializer = ApplicationSerializer(
            page, many=True, context=self.get_serializer_context()
        )
        return self.get_paginated_response(serializer.data)


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
        if not self.request.user.is_candidate:
            raise PermissionDenied("Only candidate users can create applications.")
        try:
            with transaction.atomic():
                serializer.save(candidate=self.request.user.candidate_profile)
        except IntegrityError:
            raise ValidationError({"job": "You have already applied for this job."})

    @action(detail=True, methods=["patch"], url_path="status")
    def set_status(self, request, pk=None):
        application = self.get_object()
        serializer = ApplicationStatusSerializer(application, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            ApplicationSerializer(
                application, context=self.get_serializer_context()
            ).data
        )
    
    @action(detail=True, methods=["get"])
    def resume(self, request, pk=None):
        application = self.get_object()
        if not application.resume:
            raise NotFound("This application has no resume.")
        return Response({
            "url": resume_download_url(application),
            "expires_in": settings.RESUME_URL_EXPIRE_SECONDS
        })
        

