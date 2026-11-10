"""Structured warning/field-report adapter; raw text is retained as evidence.

Extraction/OCR belongs before this adapter. It does not pretend to parse live DMC
pages or infer measurements from arbitrary prose.
"""

from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from atlas.core.events import Event, EventType


class FeedReport(BaseModel):
    report_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    kind: Literal["official_warning", "field_report"]
    area_id: str = Field(min_length=1)
    timestamp: datetime
    attribute: Literal["water_level", "rainfall", "soil_moisture", "tilt", "earthquake", "warning"]
    value: float = Field(ge=0, allow_inf_nan=False)
    unit: str
    text: str = ""
    # For a "warning": which hazard it warns of (e.g. an NBRO landslide warning). Optional; a warning
    # without one is read as a flood warning, as before.
    hazard: Literal["flood", "landslide", "earthquake"] | None = None

    @field_validator("timestamp")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Report timestamp must include timezone")
        return value


class FloodScene(BaseModel):
    """A processed radar scene is ready for an area. ``timestamp`` is the acquisition time."""

    kind: Literal["flood_scene"] = "flood_scene"
    scene_id: str = Field(min_length=1)
    area_id: str = Field(min_length=1)
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError("Scene timestamp must include timezone")
        return value


def scene_event(scene: FloodScene) -> Event:
    return Event(
        id=sha256(f"flood_scene:{scene.scene_id}:{scene.area_id}".encode()).hexdigest(),
        type=EventType.FLOOD_SCENE,
        source="radar_flood_layer",
        created_at=scene.timestamp,
        payload=scene.model_dump(mode="json"),
    )


def to_event(report: FeedReport) -> Event:
    return Event(
        id=sha256(f"{report.source}:{report.report_id}".encode()).hexdigest(),
        type=EventType.OBSERVATION,
        source=report.source,
        created_at=report.timestamp,
        payload=report.model_dump(mode="json"),
    )
