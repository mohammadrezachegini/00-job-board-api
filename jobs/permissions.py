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
