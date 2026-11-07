import pytest
from django.core.management import call_command
from drf_spectacular.generators import SchemaGenerator


@pytest.fixture(scope="module")
def schema():
    return SchemaGenerator().get_schema(request=None, public=True)


def component(schema, name):
    return schema["components"]["schemas"][name]


def ref(content):
    return content["application/json"]["schema"]["$ref"].split("/")[-1]


def test_schema_is_valid_and_has_no_warnings(tmp_path):
    out = tmp_path / "schema.yml"

    call_command("spectacular", "--validate", "--fail-on-warn", "--file", str(out))

    assert out.read_text().startswith("openapi: 3.0.3")


def test_docs_are_public(client):
    assert client.get("/api/schema/").status_code == 200
    assert client.get("/api/schema/swagger-ui/").status_code == 200


def test_jwt_bearer_auth_is_documented(schema):
    assert schema["components"]["securitySchemes"]["jwtAuth"] == {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}


def test_resume_link_operation(schema):
    responses = schema["paths"]["/api/applications/{id}/resume/"]["get"]["responses"]

    assert ref(responses["200"]["content"]) == "ResumeLink"
    assert set(component(schema, "ResumeLink")["properties"]) == {"url", "expires_in"}
    assert "404" in responses


def test_status_operation_takes_only_a_status(schema):
    operation = schema["paths"]["/api/applications/{id}/status/"]["patch"]
    request_name = ref(operation["requestBody"]["content"])

    assert "ApplicationStatus" in request_name
    assert set(component(schema, request_name)["properties"]) == {"status"}
    assert ref(operation["responses"]["200"]["content"]) == "Application"


def test_applicants_operation_is_a_paginated_application_list(schema):
    responses = schema["paths"]["/api/jobs/{id}/applications/"]["get"]["responses"]

    assert ref(responses["200"]["content"]) == "PaginatedApplicationList"


@pytest.mark.parametrize("path", ["/api/auth/register/company/", "/api/auth/register/candidate/"])
def test_registration_returns_the_user_summary(schema, path):
    responses = schema["paths"][path]["post"]["responses"]

    assert ref(responses["201"]["content"]) == "RegisteredUser"
    assert set(component(schema, "RegisteredUser")["properties"]) == {"id", "username", "email", "role"}


def test_application_fields_are_typed(schema):
    response = component(schema, "Application")["properties"]
    request = component(schema, "ApplicationRequest")["properties"]

    assert response["has_resume"]["type"] == "boolean"
    assert response["match_score"]["type"] == "integer"
    assert response["match_score"]["nullable"] is True
    assert "resume" not in response
    assert request["resume"]["format"] == "binary"