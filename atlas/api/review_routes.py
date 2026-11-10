"""Read-only dataset and model review; samples are always an explicit opt-in."""

from fastapi import APIRouter, Request

from atlas.dashboard.dev.review import data_exploration, model_review
from atlas.manager import rbac
from atlas.manager.rbac import requires

router = APIRouter(prefix="/dev")


@router.get("/data-exploration", dependencies=requires(rbac.RUN_READ))
async def datasets(sample: bool = False):
    return data_exploration(sample=sample)


@router.get(
    "/model-review",
    dependencies=(
        requires(rbac.RUN_READ) + requires(rbac.LEDGER_READ) + requires(rbac.APPROVAL_READ)
    ),
)
async def models(request: Request, sample: bool = False):
    return model_review(request.app.state.system, sample=sample)
