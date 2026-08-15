"""RFC 9457 ``application/problem+json`` error responses.

Every error this service returns — a domain error, a validation failure, an
unroutable path, or an unhandled exception — leaves through here, in the same
shape the Go service emits.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_CONTENT,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from {@ package_name @}.domain import Category, ServiceError
from {@ package_name @}.log import logger

#: The RFC 9457 media type. Every error response uses it.
PROBLEM_CONTENT_TYPE = "application/problem+json"

#: RFC 9457's default when an error has no documentation URI of its own. It is
#: written explicitly rather than omitted, so the two services produce
#: comparable error bodies.
DEFAULT_PROBLEM_TYPE = "about:blank"

#: The domain taxonomy mapped onto HTTP. This table is the transport's
#: business; the service layer never names a status code.
STATUS_FOR_CATEGORY: dict[Category, int] = {
    Category.INVALID: HTTP_400_BAD_REQUEST,
    Category.NOT_FOUND: HTTP_404_NOT_FOUND,
    Category.CONFLICT: HTTP_409_CONFLICT,
    Category.UNAUTHORIZED: HTTP_401_UNAUTHORIZED,
    Category.FORBIDDEN: HTTP_403_FORBIDDEN,
    Category.INTERNAL: HTTP_500_INTERNAL_SERVER_ERROR,
}

#: Status text, so the "title" member matches the Go service's http.StatusText.
TITLES = {
    HTTP_400_BAD_REQUEST: "Bad Request",
    HTTP_401_UNAUTHORIZED: "Unauthorized",
    HTTP_403_FORBIDDEN: "Forbidden",
    HTTP_404_NOT_FOUND: "Not Found",
    HTTP_409_CONFLICT: "Conflict",
    HTTP_422_UNPROCESSABLE_CONTENT: "Unprocessable Entity",
    HTTP_500_INTERNAL_SERVER_ERROR: "Internal Server Error",
}


class ProblemResponse(JSONResponse):
    """A JSON response carrying the problem+json media type."""

    media_type = PROBLEM_CONTENT_TYPE


def problem(
    request: Request,
    status: int,
    detail: str,
    errors: list[dict[str, Any]] | None = None,
) -> ProblemResponse:
    """Build an RFC 9457 response."""
    body: dict[str, Any] = {
        "type": DEFAULT_PROBLEM_TYPE,
        "title": TITLES.get(status, "Error"),
        "status": status,
        "detail": detail,
        "instance": request.url.path,
    }
    if errors:
        body["errors"] = errors
    return ProblemResponse(status_code=status, content=body)


def install(app: FastAPI) -> None:
    """Register the handlers that turn every failure into problem+json."""

    @app.exception_handler(ServiceError)
    async def _domain_error(request: Request, exc: ServiceError) -> ProblemResponse:
        status = STATUS_FOR_CATEGORY.get(exc.category, HTTP_500_INTERNAL_SERVER_ERROR)

        if exc.category is Category.INTERNAL:
            # The cause is recorded here and goes no further. Driver errors and
            # stack traces never cross this boundary: log the detail, return the
            # category.
            logger.opt(exception=exc.cause or exc).error(
                "request failed", category=str(exc.category)
            )
            return problem(request, status, "an unexpected error occurred")

        return problem(request, status, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> ProblemResponse:
        # FastAPI's own 422 body is {"detail": [...]}, which is not RFC 9457.
        # Remapping it here is what stops a client from being able to tell the
        # two services apart on a bad request.
        return problem(
            request,
            HTTP_422_UNPROCESSABLE_CONTENT,
            "validation failed",
            errors=[_detail(item) for item in exc.errors()],
        )

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> ProblemResponse:
        # Covers the 404 for an unroutable path and the 405 for a bad method.
        detail = str(exc.detail)
        if exc.status_code == HTTP_404_NOT_FOUND and detail == "Not Found":
            # Starlette's stock detail just repeats the title. Say which request
            # missed, as the Go service does.
            detail = f"no route matches {request.method} {request.url.path}"
        return problem(request, exc.status_code, detail)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> ProblemResponse:
        # The outermost net. The process survives; the client learns nothing
        # about what went wrong beyond the status.
        logger.opt(exception=exc).error("unhandled exception")
        return problem(request, HTTP_500_INTERNAL_SERVER_ERROR, "an unexpected error occurred")


def _detail(item: dict[str, Any]) -> dict[str, Any]:
    """Reshape one pydantic error into the shape the Go service emits.

    Pydantic reports ``{"type", "loc", "msg", "input"}``; the shared shape is
    ``{"message", "location", "value"}`` with a dotted location.
    """
    location = ".".join(str(part) for part in item.get("loc", ()))
    detail: dict[str, Any] = {"message": item.get("msg", "")}
    if location:
        detail["location"] = location
    if "input" in item:
        detail["value"] = item["input"]
    return detail
