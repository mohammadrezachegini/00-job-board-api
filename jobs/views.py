from rest_framework import generics, mixins, viewsets
from rest_framework.permissions import AllowAny

from jobs.models import Job

from .serializers import (
    CompanyRegistrationSerializer,
    CandidateRegistrationSerializer,
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

    def get_queryset(self):
        queryset = Job.objects.select_related("company")
        if self.action == "list":
            queryset = queryset.filter(is_open=True)
        return queryset
    
    def perform_create(self, serializer):
        if not self.request.user.is_company:
            raise PermissionError("Only company users can create jobs.")
        serializer.save(company=self.request.user.company)