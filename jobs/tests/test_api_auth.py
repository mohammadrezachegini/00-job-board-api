import pytest
from rest_framework.test import APIClient

from jobs.models import CandidateProfile, Company, User

STRONG = "s3cure-pass-2026"
COMPANY = {"username": "newco", "email": "Hello@NewCo.test", "password": STRONG, "company_name": "NewCo"}
CANDIDATE = {"username": "ana", "email": "ana@example.test", "password": STRONG, "skills": ["AWS", "Go"]}


def post(path, data, **extra):
    return APIClient().post(path, data, format="json", **extra)


# ---------- registration ----------


def test_company_registration_creates_user_and_unverified_company(db):
    response = post("/api/auth/register/company/", COMPANY)
    body = response.json()

    assert response.status_code == 201
    assert body["role"] == "company"
    assert body["email"] == "hello@newco.test"
    assert "password" not in body
    company = Company.objects.get(user__username="newco")
    assert company.name == "NewCo"
    assert company.is_verified is False


def test_candidate_registration_creates_profile(db):
    response = post("/api/auth/register/candidate/", CANDIDATE)

    assert response.status_code == 201
    assert response.json()["role"] == "candidate"
    assert CandidateProfile.objects.get(user__username="ana").skills == ["AWS", "Go"]


def test_client_cannot_choose_role_or_staff(db):
    response = post("/api/auth/register/candidate/", {**CANDIDATE, "role": "company", "is_staff": True})
    user = User.objects.get(username="ana")

    assert response.status_code == 201
    assert user.role == User.Role.CANDIDATE
    assert user.is_staff is False


def test_password_is_hashed(db):
    post("/api/auth/register/candidate/", CANDIDATE)
    user = User.objects.get(username="ana")

    assert user.password != STRONG
    assert user.check_password(STRONG)


@pytest.mark.parametrize(
    ("changes", "field"),
    [({"username": "SAM"}, "username"), ({"email": "SAM@Example.test"}, "email")],
)
def test_duplicates_are_rejected_case_insensitively(make_candidate, changes, field):
    make_candidate("sam")
    response = post("/api/auth/register/candidate/", {**CANDIDATE, **changes})

    assert response.status_code == 400
    assert field in response.json()


@pytest.mark.parametrize("password", ["12345678", "password", "short"])
def test_weak_passwords_are_rejected(db, password):
    response = post("/api/auth/register/candidate/", {**CANDIDATE, "password": password})

    assert response.status_code == 400
    assert "password" in response.json()
    assert not User.objects.filter(username="ana").exists()


def test_company_registration_is_atomic(db, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("database hiccup")

    monkeypatch.setattr(Company.objects, "create", boom)

    with pytest.raises(RuntimeError):
        post("/api/auth/register/company/", COMPANY)

    assert not User.objects.filter(username="newco").exists()


def test_registration_ignores_a_bad_token(db):
    response = post("/api/auth/register/candidate/", CANDIDATE, HTTP_AUTHORIZATION="Bearer garbage")

    assert response.status_code == 201


# ---------- JWT ----------


def login(username, password="test-pass-123"):
    return post("/api/auth/token/", {"username": username, "password": password})


def bearer(token):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


def test_login_returns_access_and_refresh(make_candidate):
    make_candidate("sam")
    response = login("sam")

    assert response.status_code == 200
    assert set(response.json()) == {"access", "refresh"}


def test_access_token_opens_protected_endpoints(make_candidate):
    make_candidate("sam")
    access = login("sam").json()["access"]

    assert bearer(access).get("/api/jobs/").status_code == 200


def test_wrong_password_gets_401(make_candidate):
    make_candidate("sam")

    assert login("sam", "wrong-password").status_code == 401


def test_garbage_token_gets_401(db):
    assert bearer("not-a-jwt").get("/api/jobs/").status_code == 401


def test_refresh_gives_a_working_access_token(make_candidate):
    make_candidate("sam")
    refresh = login("sam").json()["refresh"]

    response = post("/api/auth/token/refresh/", {"refresh": refresh})

    assert response.status_code == 200
    assert bearer(response.json()["access"]).get("/api/jobs/").status_code == 200


def test_refresh_token_is_not_an_access_token(make_candidate):
    make_candidate("sam")
    refresh = login("sam").json()["refresh"]

    assert bearer(refresh).get("/api/jobs/").status_code == 401