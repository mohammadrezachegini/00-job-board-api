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


import os
import subprocess
import sys

from django.conf import settings as django_settings

AWS_ONLY = ("AWS_REGION", "AWS_SQS_ENDPOINT_URL", "SQS_QUEUE_NAME", "AWS_STORAGE_BUCKET_NAME",
            "AWS_S3_ENDPOINT_URL", "AWS_S3_PUBLIC_ENDPOINT_URL")
AZURE_ONLY = ("AZURE_ACCOUNT_NAME", "AZURE_ACCOUNT_KEY", "AZURE_CONTAINER", "AZURE_BLOB_ENDPOINT",
              "AZURE_PUBLIC_BLOB_ENDPOINT", "SERVICE_BUS_CONNECTION_STRING", "SERVICE_BUS_QUEUE_NAME")
PRINT = (
    "import django; django.setup(); from django.conf import settings as s; "
    "print(s.STORAGES['default']['BACKEND'], hasattr(s, 'SQS_QUEUE_NAME'), hasattr(s, 'SERVICE_BUS_QUEUE_NAME'))"
)


def load_settings(provider, remove):
    env = {k: v for k, v in os.environ.items() if k not in remove}
    env["CLOUD_PROVIDER"] = provider
    env["DJANGO_SETTINGS_MODULE"] = "config.settings"
    return subprocess.run(
        [sys.executable, "-c", PRINT], env=env, cwd=django_settings.BASE_DIR,
        capture_output=True, text=True, timeout=60,
    )


def test_azure_starts_without_any_aws_variable():
    result = load_settings("azure", remove=AWS_ONLY)

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["storages.backends.azure_storage.AzureStorage", "False", "True"]


def test_aws_starts_without_any_azure_variable():
    result = load_settings("aws", remove=AZURE_ONLY)

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["storages.backends.s3.S3Storage", "True", "False"]


def test_azure_fails_fast_when_its_own_variable_is_missing():
    result = load_settings("azure", remove=AWS_ONLY + ("SERVICE_BUS_CONNECTION_STRING",))

    assert result.returncode != 0
    assert "SERVICE_BUS_CONNECTION_STRING" in result.stderr
