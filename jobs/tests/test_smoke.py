from django.contrib.auth import get_user_model


def test_healthz(client):
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_test_database_starts_empty(db):
    assert get_user_model().objects.count() == 0