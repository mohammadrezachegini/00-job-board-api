import pytest

from jobs.models import Job

NEW_JOB = {
    "title": "SRE Intern",
    "description": "Keep it running.",
    "location": "Remote",
}


@pytest.fixture
def acme(make_company):
    return make_company("acme")


def test_create_normalises_skills_and_takes_company_from_the_user(
    api_as, acme, make_company
):
    make_company("globex")
    response = api_as(acme.user).post(
        "/api/jobs/",
        {**NEW_JOB, "required_skills": [" Python ", "AWS", "aws"], "company": "Globex"},
        format="json",
    )
    body = response.json()

    assert response.status_code == 201
    assert body["required_skills"] == ["python", "aws"]
    assert body["company"] == "Acme"
    assert Job.objects.get(id=body["id"]).company == acme


def test_update_normalises_skills(api_as, acme, make_job):
    job = make_job(acme)
    response = api_as(acme.user).patch(
        f"/api/jobs/{job.id}/", {"required_skills": ["Go", "GO "]}, format="json"
    )

    assert response.status_code == 200
    assert response.json()["required_skills"] == ["go"]


def test_blank_skill_is_rejected(api_as, acme):
    response = api_as(acme.user).post(
        "/api/jobs/", {**NEW_JOB, "required_skills": ["aws", "  "]}, format="json"
    )

    assert response.status_code == 400
    assert "required_skills" in response.json()


def test_missing_fields_are_reported(api_as, acme):
    response = api_as(acme.user).post("/api/jobs/", {}, format="json")

    assert response.status_code == 400
    assert {"title", "description", "location"} <= set(response.json())


def test_invalid_job_type_is_rejected(api_as, acme):
    response = api_as(acme.user).post(
        "/api/jobs/", {**NEW_JOB, "job_type": "forever"}, format="json"
    )

    assert response.status_code == 400
    assert "job_type" in response.json()


def test_closed_jobs_are_hidden_from_the_list_but_not_from_detail(
    api_as, acme, make_job
):
    closed = make_job(acme, title="Closed Role", is_open=False)
    client = api_as(acme.user)

    titles = [job["title"] for job in client.get("/api/jobs/").json()["results"]]

    assert "Closed Role" not in titles
    assert client.get(f"/api/jobs/{closed.id}/").status_code == 200


# ---------- filters, search, ordering ----------


@pytest.fixture
def board(acme, make_company, make_job):
    globex = make_company("globex")
    make_job(
        acme,
        title="Junior DevOps Engineer",
        required_skills=["aws", "terraform"],
        location="Vancouver, BC",
    )
    make_job(
        globex,
        title="Data Analyst",
        required_skills=["python", "sql"],
        location="Toronto",
        job_type="contract",
    )
    make_job(
        acme,
        title="SRE Intern",
        required_skills=["python", "kubernetes"],
        location="Remote",
        job_type="internship",
    )
    make_job(acme, title="Closed Role", required_skills=["aws"], is_open=False)
    return acme


def titles(response):
    return [job["title"] for job in response.json()["results"]]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, ["Data Analyst", "Junior DevOps Engineer", "SRE Intern"]),
        ({"job_type": "contract"}, ["Data Analyst"]),
        ({"location": "vancouver"}, ["Junior DevOps Engineer"]),
        ({"skills": "python"}, ["Data Analyst", "SRE Intern"]),
        ({"skills": " AWS , Go "}, ["Junior DevOps Engineer"]),
        (
            {"skills": "python,terraform"},
            ["Data Analyst", "Junior DevOps Engineer", "SRE Intern"],
        ),
        ({"search": "acme"}, ["Junior DevOps Engineer", "SRE Intern"]),
        ({"search": "analyst"}, ["Data Analyst"]),
        ({"job_type": "contract", "skills": "python"}, ["Data Analyst"]),
    ],
)
def test_filters_and_search(api_as, board, params, expected):
    response = api_as(board.user).get("/api/jobs/", params)

    assert response.status_code == 200
    assert sorted(titles(response)) == expected


def test_invalid_filter_value_is_a_400(api_as, board):
    assert (
        api_as(board.user).get("/api/jobs/", {"job_type": "forever"}).status_code == 400
    )


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, ["SRE Intern", "Data Analyst", "Junior DevOps Engineer"]),
        (
            {"ordering": "title"},
            ["Data Analyst", "Junior DevOps Engineer", "SRE Intern"],
        ),
        (
            {"ordering": "-title"},
            ["SRE Intern", "Junior DevOps Engineer", "Data Analyst"],
        ),
        (
            {"ordering": "password"},
            ["SRE Intern", "Data Analyst", "Junior DevOps Engineer"],
        ),
    ],
)
def test_ordering(api_as, board, params, expected):
    assert titles(api_as(board.user).get("/api/jobs/", params)) == expected


def test_pagination(api_as, acme, make_job):
    for i in range(21):
        make_job(acme, title=f"Job {i:02d}")
    client = api_as(acme.user)

    first = client.get("/api/jobs/").json()
    second = client.get("/api/jobs/", {"page": 2}).json()

    assert first["count"] == 21
    assert len(first["results"]) == 20
    assert first["next"].endswith("page=2")
    assert len(second["results"]) == 1
    assert second["next"] is None


def test_skills_filter_with_only_commas_returns_everything(api_as, board):
    response = api_as(board.user).get("/api/jobs/", {"skills": " , ,"})

    assert sorted(titles(response)) == ["Data Analyst", "Junior DevOps Engineer", "SRE Intern"]
