"""Business logic: rules and error categories."""

from __future__ import annotations

import pytest

from widget_svc.errors import Category, ConflictError, InvalidError, NotFoundError, ServiceError
from widget_svc.service import NewWidget, Widgets


@pytest.mark.parametrize(
    ("name", "colour", "expected_name", "expected_error"),
    [
        pytest.param("sprocket", "red", "sprocket", None, id="valid"),
        pytest.param("  sprocket  ", "blue", "sprocket", None, id="trims surrounding whitespace"),
        pytest.param("   ", "red", None, InvalidError, id="blank name is invalid"),
    ],
)
async def test_create_widget(
    widgets: Widgets,
    name: str,
    colour: str,
    expected_name: str | None,
    expected_error: type[ServiceError] | None,
) -> None:
    if expected_error is not None:
        with pytest.raises(expected_error) as raised:
            await widgets.create(NewWidget(name=name, color=colour))  # type: ignore[arg-type]
        assert raised.value.category is Category.INVALID
        return

    created = await widgets.create(NewWidget(name=name, color=colour))  # type: ignore[arg-type]
    assert created.name == expected_name
    assert created.id
    assert created.created_at


async def test_create_widget_rejects_duplicate_name(widgets: Widgets) -> None:
    await widgets.create(NewWidget(name="sprocket", color="red"))

    # The duplicate check is case-insensitive, so this must collide.
    with pytest.raises(ConflictError) as raised:
        await widgets.create(NewWidget(name="SPROCKET", color="blue"))

    assert raised.value.category is Category.CONFLICT


async def test_get_widget(widgets: Widgets) -> None:
    created = await widgets.create(NewWidget(name="sprocket", color="red"))

    assert await widgets.get(created.id) == created


async def test_get_widget_missing(widgets: Widgets) -> None:
    with pytest.raises(NotFoundError) as raised:
        await widgets.get("no-such-id")

    assert raised.value.category is Category.NOT_FOUND


async def test_list_widgets_is_ordered_oldest_first(widgets: Widgets) -> None:
    for name in ("first", "second", "third"):
        await widgets.create(NewWidget(name=name, color="red"))

    assert [w.name for w in await widgets.list()] == ["first", "second", "third"]


async def test_list_widgets_is_empty_not_none(widgets: Widgets) -> None:
    assert await widgets.list() == []


def test_unknown_exception_is_internal() -> None:
    # Anything that is not a domain error is an internal one — the transport
    # must never turn an unexpected failure into a 4xx.
    assert ServiceError("boom").category is Category.INTERNAL


def test_shape_violations_are_rejected_before_the_service_sees_them() -> None:
    # An unknown colour never reaches Widgets.create: the model rejects it, which
    # is what produces the 422 rather than a 400.
    with pytest.raises(ValueError, match="color"):
        NewWidget(name="sprocket", color="puce")  # type: ignore[arg-type]
