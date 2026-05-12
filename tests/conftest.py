# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Contributors to device-inventory-fastapi
# https://github.com/fidpa/device-inventory-fastapi
"""Shared pytest fixtures for the device-inventory-fastapi test suite."""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterator

import bcrypt
import pytest

TEST_PASSWORD = "test-password-for-suite"
TEST_PASSWORD_HASH = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
TEST_AUTH_SECRET = secrets.token_hex(32)


@pytest.fixture(scope="session", autouse=True)
def _set_environment(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Configure environment variables required by src.app at import time."""
    tmpdir = tmp_path_factory.mktemp("inventory-test")
    db_dir = tmpdir / "db"
    db_dir.mkdir(exist_ok=True)

    os.environ["AUTH_PASSWORD_HASH"] = TEST_PASSWORD_HASH
    os.environ["AUTH_SECRET"] = TEST_AUTH_SECRET
    os.environ["NEXTCLOUD_URL"] = "https://cloud.example.com"
    os.environ["NEXTCLOUD_USER"] = "sysinfo"
    os.environ["NEXTCLOUD_PASSWORD"] = "test-app-password"
    os.environ["NEXTCLOUD_PATH"] = "/remote.php/dav/files/sysinfo/inbox"

    yield


@pytest.fixture
def client():
    """Return a TestClient bound to the FastAPI app."""
    from fastapi.testclient import TestClient

    from src import app as app_module

    return TestClient(app_module.app)


@pytest.fixture
def auth_password() -> str:
    """The plain-text password matching TEST_PASSWORD_HASH."""
    return TEST_PASSWORD


@pytest.fixture
def auth_cookie(client, auth_password) -> str:
    """A logged-in session cookie value."""
    response = client.post(
        "/login",
        data={"password": auth_password},
        follow_redirects=False,
    )
    cookie_name = "inventory_auth"
    return response.cookies.get(cookie_name) or ""
