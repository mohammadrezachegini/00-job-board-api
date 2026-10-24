from rest_framework import generics
from rest_framework.permissions import AllowAny

from .serializers import CompanyRegistrationSerializer, CandidateRegistrationSerializer


class CompanyRegisterView(generics.CreateAPIView):
    serializer_class = CompanyRegistrationSerializer
    permission_classes = [AllowAny]
    authentication_classes = []


class CandidateRegisterView(generics.CreateAPIView):
    serializer_class = CandidateRegistrationSerializer
    permission_classes = [AllowAny]
    authentication_classes = []
