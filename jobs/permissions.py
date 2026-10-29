from rest_framework.permissions import BasePermission


class IsVerifiedCompany(BasePermission):
    message = "Only company accounts can do this."

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated or not user.is_company:
            return False
        company = getattr(user, "company", None)
        if company is None or not company.is_verified:
            self.message = "Your company account is not verified."
            return False
        return True


class IsCandidate(BasePermission):
    message = "Only candidate accounts can do this."

    def has_permission(self, request, view):
        user = request.user
        return (
            user.is_authenticated
            and user.is_candidate
            and hasattr(user, "candidate_profile")
        )


class IsJobOwner(BasePermission):
    message = "Only the company that posted this job can do this."

    def has_object_permission(self, request, view, obj):
        company = getattr(request.user, "company", None)
        return company is not None and obj.company_id == company.id


class IsApplicantOwner(BasePermission):
    message = "You don't have access to this application."

    def has_object_permission(self, request, view, obj):
        profile = getattr(request.user, "candidate_profile", None)
        if profile is not None and obj.candidate_id == profile.id:
            return True
        company = getattr(request.user, "company", None)
        return company is not None and obj.job.company_id == company.id
