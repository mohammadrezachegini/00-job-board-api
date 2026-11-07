import pytest
from django.core.exceptions import ImproperlyConfigured

from config.settings import env, env_bool, env_list

NAME = "JOBBOARD_TEST_SETTING"


@pytest.mark.parametrize("value", [None, ""])
def test_required_setting_missing_or_empty_raises(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(NAME, raising=False)
    else:
        monkeypatch.setenv(NAME, value)

    with pytest.raises(ImproperlyConfigured, match=f"Missing required environment variable: {NAME}"):
        env(NAME)


def test_optional_setting_uses_the_default_when_missing_or_empty(monkeypatch):
    monkeypatch.delenv(NAME, raising=False)
    assert env(NAME, "fallback") == "fallback"

    monkeypatch.setenv(NAME, "")
    assert env(NAME, "fallback") == "fallback"

    monkeypatch.setenv(NAME, "real")
    assert env(NAME, "fallback") == "real"


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("true", True), (" Yes ", True), ("on", True), ("False", False), ("0", False), ("ture", False)],
)
def test_env_bool(monkeypatch, value, expected):
    monkeypatch.setenv(NAME, value)
    assert env_bool(NAME) is expected


def test_env_bool_default(monkeypatch):
    monkeypatch.delenv(NAME, raising=False)
    assert env_bool(NAME) is False
    assert env_bool(NAME, True) is True


def test_env_list(monkeypatch):
    monkeypatch.setenv(NAME, " localhost, 127.0.0.1 ,,10.0.0.149 ,")
    assert env_list(NAME) == ["localhost", "127.0.0.1", "10.0.0.149"]

    monkeypatch.delenv(NAME)
    assert env_list(NAME) == []
    assert env_list(NAME, "a,b") == ["a", "b"]
