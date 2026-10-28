from django.db import IntegrityError, transaction
from rest_framework import generics, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from .permissions import IsVerifiedCompany, IsCandidate

from .models import Application, Job
from .serializers import (
    ApplicationSerializer,
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
    
    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsVerifiedCompany()]
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


class ApplicationViewSet(mixins.CreateModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ApplicationSerializer
    queryset = Application.objects.select_related("job__company", "candidate__user")
    
    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated(), IsCandidate()]
        return super().get_permissions()
    
    def perform_create(self, serializer):
        if not self.request.user.is_candidate:
            raise PermissionDenied("Only candidate users can create applications.")
        try:
            with transaction.atomic():
                serializer.save(candidate=self.request.user.candidate_profile)
        except IntegrityError:
            raise ValidationError({"job": "You have already applied for this job."})
        