"""The visitor cookie (ADR-11.1)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.visitors import VISITOR_COOKIE, VISITOR_COOKIE_MAX_AGE, new_visitor_id


def test_a_new_browser_gets_an_http_only_visitor_cookie(client: TestClient) -> None:
    response = client.get("/api/recommendations")

    cookie = response.headers["set-cookie"]
    visitor_id = client.cookies[VISITOR_COOKIE]
    assert len(visitor_id) == 43
    assert cookie.startswith(f"{VISITOR_COOKIE}={visitor_id};")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/api" in cookie
    assert f"Max-Age={VISITOR_COOKIE_MAX_AGE}" in cookie
    assert "Secure" not in cookie  # plain HTTP, as when run locally


def test_a_known_visitor_keeps_its_cookie(client: TestClient) -> None:
    client.get("/api/recommendations")
    visitor_id = client.cookies[VISITOR_COOKIE]

    response = client.get("/api/recommendations")

    assert "set-cookie" not in response.headers
    assert client.cookies[VISITOR_COOKIE] == visitor_id


def test_a_forged_cookie_is_replaced(client: TestClient) -> None:
    client.cookies.set(VISITOR_COOKIE, "admin")

    response = client.get("/api/recommendations")

    issued = response.headers["set-cookie"].split(";")[0]
    assert issued.startswith(f"{VISITOR_COOKIE}=")
    assert issued != f"{VISITOR_COOKIE}=admin"


def test_cookie_is_secure_over_https(app: FastAPI) -> None:
    # Behind the proxies, uvicorn takes the https scheme from X-Forwarded-Proto.
    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/api/recommendations")

    assert "Secure" in response.headers["set-cookie"]


def test_visitor_ids_are_random() -> None:
    assert len({new_visitor_id() for _ in range(100)}) == 100
