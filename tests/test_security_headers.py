# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Contributors to device-inventory-fastapi
# https://github.com/fidpa/device-inventory-fastapi
"""Tests for the SecurityHeaders middleware."""


def test_security_headers_present_on_login(client):
    """Security headers appear on every response, including unauthenticated ones."""
    response = client.get("/login")

    # Core security headers expected from a hardened web app
    expected_headers = [
        "x-frame-options",
        "x-content-type-options",
        "referrer-policy",
    ]
    headers = {k.lower() for k in response.headers}
    for header in expected_headers:
        assert header in headers, f"Missing security header: {header}"


def test_x_frame_options_blocks_iframes(client):
    """X-Frame-Options should be DENY or SAMEORIGIN to prevent click-jacking."""
    response = client.get("/login")
    value = response.headers.get("x-frame-options", "").upper()
    assert value in {"DENY", "SAMEORIGIN"}


def test_content_type_options_nosniff(client):
    """X-Content-Type-Options should be nosniff."""
    response = client.get("/login")
    assert response.headers.get("x-content-type-options", "").lower() == "nosniff"
