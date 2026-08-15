"""The widget routes.

Handlers parse a request, validate its *shape* (FastAPI does that from the type
annotations), call the service layer, and return a model. Business rules live in
:mod:`widget_svc.service`, not here.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Request, status

from widget_svc.api.problem import PROBLEM_CONTENT_TYPE
from widget_svc.service import NewWidget, Widget, Widgets


def get_widgets(request: Request) -> Widgets:
    """Hand the handler the service the composition root built."""
    widgets: Widgets = request.app.state.widgets
    return widgets


WidgetsDep = Annotated[Widgets, Depends(get_widgets)]

#: Documents an error response without restating its schema at each use.
_PROBLEM: dict[str, Any] = {"content": {PROBLEM_CONTENT_TYPE: {}}}

# Starlette matches routes in registration order, unlike Go's ServeMux, which
# picks the most specific match. If a literal subpath is ever added — say
# /widgets/search — it must be registered BEFORE /widgets/{widget_id}, or the
# parameterised route swallows it.
router = APIRouter(prefix="/widgets", tags=["widgets"])


@router.get(
    "",
    operation_id="widgets.list",
    summary="List widgets",
    description="Returns every widget, oldest first.",
)
async def list_widgets(widgets: WidgetsDep) -> list[Widget]:
    return await widgets.list()


@router.get(
    "/{id}",
    operation_id="widgets.get",
    summary="Fetch a widget by ID",
    responses={status.HTTP_404_NOT_FOUND: _PROBLEM},
)
async def get_widget(
    widgets: WidgetsDep,
    # The path parameter is "id" because the route template is part of the API
    # contract and must match the Go service's. The Python name is aliased so
    # the handler does not shadow the builtin.
    widget_id: Annotated[
        str, Path(alias="id", min_length=1, max_length=64, description="Widget identifier.")
    ],
) -> Widget:
    return await widgets.get(widget_id)


@router.post(
    "",
    operation_id="widgets.create",
    summary="Create a widget",
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_400_BAD_REQUEST: _PROBLEM,
        status.HTTP_409_CONFLICT: _PROBLEM,
    },
)
async def create_widget(widgets: WidgetsDep, new: NewWidget) -> Widget:
    return await widgets.create(new)
