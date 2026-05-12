# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Contributors to device-inventory-fastapi
# https://github.com/fidpa/device-inventory-fastapi
"""Smoke tests for the health endpoint."""


def test_health_returns_ok(client):
    """/health returns 200 OK regardless of authentication."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.text.strip() == "OK"


def test_health_does_not_require_auth(client):
    """/health is in AUTH_SKIP — no cookie needed."""
    # Explicitly clear cookies
    client.cookies.clear()
    response = client.get("/health")
    assert response.status_code == 200
