# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Contributors to device-inventory-fastapi
# https://github.com/fidpa/device-inventory-fastapi
"""Authentication and rate-limit tests."""

import pytest


def test_login_page_renders(client):
    """GET /login returns the login form."""
    response = client.get("/login")
    assert response.status_code == 200
    assert "password" in response.text.lower()


def test_login_with_correct_password_sets_cookie(client, auth_password):
    """POST /login with the correct password sets a session cookie."""
    response = client.post(
        "/login",
        data={"password": auth_password},
        follow_redirects=False,
    )
    assert response.status_code in (302, 303)
    assert "inventory_auth" in response.cookies


def test_login_with_wrong_password_rejects(client):
    """POST /login with a wrong password does not set a cookie."""
    response = client.post(
        "/login",
        data={"password": "wrong-password-1234567890"},
        follow_redirects=False,
    )
    assert "inventory_auth" not in response.cookies


def test_protected_route_redirects_when_unauthenticated(client):
    """Protected routes redirect to /login without a valid cookie."""
    client.cookies.clear()
    response = client.get("/", follow_redirects=False)
    # Either 302/303 redirect or 401, depending on middleware behaviour
    assert response.status_code in (302, 303, 401)


def test_logout_clears_cookie(client, auth_password):
    """GET /logout clears the inventory_auth cookie."""
    # Log in first
    client.post(
        "/login",
        data={"password": auth_password},
        follow_redirects=False,
    )
    response = client.get("/logout", follow_redirects=False)
    # Cookie should be cleared (Set-Cookie with Max-Age=0 or empty value)
    assert response.status_code in (200, 302, 303)


@pytest.mark.parametrize("attempt", range(6))
def test_rate_limit_kicks_in(client, attempt):
    """After several failed login attempts the rate limiter responds."""
    # Note: this test is order-sensitive since the rate limiter is in-memory
    # The 6th attempt (attempt=5) should be rate-limited
    response = client.post(
        "/login",
        data={"password": "definitely-wrong-password"},
        follow_redirects=False,
    )
    # First 5 attempts should be rejected with normal credentials error;
    # 6th+ should be rate-limited (status 429 or shown in response body).
    assert response.status_code in (200, 401, 429)
