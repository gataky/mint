"""Reading RFC 9457 back off the wire.

The parse is total by design: a peer that answers with something unexpected must
not turn a recoverable upstream failure into an unrecoverable local one.
"""

from __future__ import annotations

import json

import pytest

from mint_client.problem import Problem, parse_problem

PROBLEM = "application/problem+json"


def encode(body: object) -> bytes:
    return json.dumps(body).encode()


def test_a_full_problem_document_is_parsed() -> None:
    body = {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "detail": 'no widget with id "abc"',
        "instance": "/widgets/abc",
    }
    problem = parse_problem(PROBLEM, encode(body))

    assert problem is not None
    assert problem.status == 404
    assert problem.detail == 'no widget with id "abc"'
    assert problem.instance == "/widgets/abc"


def test_the_validation_errors_array_is_parsed() -> None:
    body = {
        "type": "about:blank",
        "title": "Unprocessable Entity",
        "status": 422,
        "detail": "validation failed",
        "errors": [{"message": "field required", "location": "body.name", "value": None}],
    }
    problem = parse_problem(PROBLEM, encode(body))

    assert problem is not None
    assert len(problem.errors) == 1
    assert problem.errors[0].location == "body.name"


def test_extension_members_are_kept() -> None:
    """RFC 9457 §3.2 permits them, and they are often the only machine-readable part."""
    problem = parse_problem(PROBLEM, encode({"status": 429, "quota_reset_at": "2026-01-01"}))

    assert problem is not None
    assert problem.model_extra is not None
    assert problem.model_extra["quota_reset_at"] == "2026-01-01"


def test_a_content_type_with_parameters_is_still_recognised() -> None:
    problem = parse_problem(f"{PROBLEM}; charset=utf-8", encode({"status": 500}))
    assert problem is not None


@pytest.mark.parametrize(
    ("content_type", "body"),
    [
        ("text/html", b"<html>nope</html>"),
        ("application/problem+json", b"not json at all"),
        ("application/problem+json", encode(["a", "list"])),
        ("", b""),
    ],
)
def test_anything_unreadable_yields_none_rather_than_raising(
    content_type: str, body: bytes
) -> None:
    assert parse_problem(content_type, body) is None


def test_plain_json_is_accepted_when_it_looks_like_a_problem() -> None:
    # Some peers label problem documents application/json. Accommodated.
    problem = parse_problem("application/json", encode({"status": 500, "detail": "boom"}))
    assert problem is not None
    assert problem.detail == "boom"


def test_plain_json_that_is_not_a_problem_is_rejected() -> None:
    """A bare {"error": "..."} must not become an all-empty Problem.

    That would read to a caller as "the upstream sent a problem document and
    every field in it was blank", rather than the truth: it does not speak
    RFC 9457.
    """
    assert parse_problem("application/json", encode({"error": "boom"})) is None


def test_the_string_form_prefers_detail() -> None:
    assert str(Problem(status=404, title="Not Found", detail="no widget")) == "no widget"


def test_the_string_form_falls_back_to_title_then_status() -> None:
    assert str(Problem(status=404, title="Not Found")) == "Not Found"
    assert str(Problem(status=404)) == "HTTP 404"
