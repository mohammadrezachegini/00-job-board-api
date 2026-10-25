from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import CandidateRegisterView, CompanyRegisterView, JobViewSet, ApplicationViewSet


router = DefaultRouter()
router.register("jobs", JobViewSet, basename="job")
router.register("applications", ApplicationViewSet, basename="application")

urlpatterns = [
    path("auth/register/company/", CompanyRegisterView.as_view(), name="register_company"),
    path("auth/register/candidate/", CandidateRegisterView.as_view(), name="register_candidate"),
    path("auth/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
] + router.urls