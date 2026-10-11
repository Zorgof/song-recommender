"""Anonymous visitors: each browser gets a random id in an HttpOnly cookie (ADR-11.1).

The app has no accounts. The visitor id scopes the history, feedback, clarification answers
and daily limits to one browser, so visitors of a public deployment do not see each other's
descriptions. Clearing cookies or opening a private window starts a new visitor.
"""

import re
import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request, Response

VISITOR_COOKIE = "sr_visitor"
# The longest cookie lifetime browsers accept (400 days).
VISITOR_COOKIE_MAX_AGE = 400 * 24 * 60 * 60
# Only ids this module issued (secrets.token_urlsafe(32)) are accepted.
_VISITOR_ID = re.compile(r"[A-Za-z0-9_-]{43}")


def new_visitor_id() -> str:
    return secrets.token_urlsafe(32)


async def identify_visitor(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Middleware: read the visitor id from the cookie, or issue a new one."""
    cookie = request.cookies.get(VISITOR_COOKIE)
    issued = cookie is None or _VISITOR_ID.fullmatch(cookie) is None
    visitor_id = new_visitor_id() if cookie is None or issued else cookie
    request.state.visitor_id = visitor_id
    response = await call_next(request)
    if issued:
        response.set_cookie(
            VISITOR_COOKIE,
            visitor_id,
            max_age=VISITOR_COOKIE_MAX_AGE,
            path="/api",
            # The page's scripts never need it.
            httponly=True,
            samesite="lax",
            # The scheme comes from X-Forwarded-Proto (uvicorn --proxy-headers): plain HTTP is
            # only used locally, where a Secure cookie would not be sent back by every browser.
            secure=request.url.scheme == "https",
        )
    return response
