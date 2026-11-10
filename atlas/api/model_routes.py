"""Read-only view of the model registry and of individual predictions (for model review)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from atlas.manager import rbac
from atlas.manager.rbac import requires

router = APIRouter()


@router.get("/models", dependencies=requires(rbac.RUN_READ))
async def list_models(request: Request, name: str | None = None):
    return [m.model_dump(mode="json") for m in request.app.state.runtime.models.list(name)]


@router.get("/predictions/{prediction_id}", dependencies=requires(rbac.LEDGER_READ))
async def get_prediction(prediction_id: str, request: Request):
    trace = request.app.state.runtime.inference.trace(prediction_id)
    if trace is None:
        raise HTTPException(404, "unknown prediction")
    return trace
