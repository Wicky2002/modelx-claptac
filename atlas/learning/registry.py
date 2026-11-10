"""Model registry: which trained model versions exist and which one is allowed to answer.

Not ``atlas.manager.registry``, which tracks agents. A version's record (feature schema, dataset
versions, metrics, operating threshold) is fixed once registered; only its status moves, and every
move is a ledger record. Weights are never stored here, only a reference to where they live.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from atlas.core.storage import Database
from atlas.memory.ledger import Ledger, canonical


class ModelStatus(str, Enum):
    CANDIDATE = "candidate"  # registered, answers nobody
    SHADOW = "shadow"  # may run beside the live model; its output is never acted on
    LIVE = "live"  # the one version that answers predict()
    RETIRED = "retired"


TRANSITIONS: dict[ModelStatus, set[ModelStatus]] = {
    ModelStatus.CANDIDATE: {ModelStatus.SHADOW, ModelStatus.RETIRED},
    ModelStatus.SHADOW: {ModelStatus.LIVE, ModelStatus.RETIRED},
    ModelStatus.LIVE: {ModelStatus.RETIRED},
    ModelStatus.RETIRED: set(),
}


class RegistryError(ValueError):
    """A registration or status change the registry refuses."""


class FeatureSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["float", "int", "str", "bool"]
    # Missing data must stay distinguishable from zero (proposal §5.2), so a feature that may be
    # missing says so and arrives as None rather than as a filled-in default.
    nullable: bool = False


class ModelSpec(BaseModel):
    """What a trainer submits. Every field is required: an undocumented model cannot be registered."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    version: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    task: str = Field(min_length=1)
    feature_schema: dict[str, FeatureSpec] = Field(min_length=1)
    dataset_versions: dict[str, str] = Field(min_length=1)
    metrics: dict[str, float] = Field(min_length=1)
    # Required but may be None for a model with no decision threshold (e.g. a multi-class classifier).
    operating_threshold: float | None
    artifact_uri: str | None = None


class ModelRecord(ModelSpec):
    status: ModelStatus
    registered_at: datetime
    updated_at: datetime


class ModelRegistry:
    def __init__(self, db: Database, ledger: Ledger, *, clock=None):
        self.db, self.ledger = db, ledger
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        db.connection.executescript("""
            CREATE TABLE IF NOT EXISTS model_versions (
                name TEXT NOT NULL, version TEXT NOT NULL, spec TEXT NOT NULL,
                status TEXT NOT NULL, registered_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (name, version));
            CREATE UNIQUE INDEX IF NOT EXISTS model_versions_one_live
                ON model_versions(name) WHERE status = 'live';
        """)

    def register(self, spec: ModelSpec) -> ModelRecord:
        """Add a version as a candidate. Repeating the same spec is a no-op; changing it is refused."""
        body = canonical(spec.model_dump(mode="json"))
        now = self.clock()
        with self.db.transaction():
            row = self._row(spec.name, spec.version)
            if row is not None:
                if row["spec"] != body:
                    raise RegistryError(f"{spec.name} {spec.version} already registered differently")
                return self._record(row)
            self.db.connection.execute(
                "INSERT INTO model_versions VALUES (?,?,?,?,?,?)",
                (
                    spec.name,
                    spec.version,
                    body,
                    ModelStatus.CANDIDATE.value,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            self.ledger.append(
                f"model:{spec.name}:{spec.version}:registered",
                "model",
                {"phase": "registered", "at": now.isoformat(), **json.loads(body)},
            )
            return self._record(self._row(spec.name, spec.version))

    def set_status(
        self, name: str, version: str, status: ModelStatus, *, actor: str, reason: str = ""
    ) -> ModelRecord:
        """Move one version along its lifecycle. A new live version retires the previous one."""
        with self.db.transaction():
            row = self._row(name, version)
            if row is None:
                raise RegistryError(f"unknown model {name} {version}")
            current = ModelStatus(row["status"])
            if status not in TRANSITIONS[current]:
                raise RegistryError(f"{name} {version}: {current.value} -> {status.value} refused")
            if status is ModelStatus.LIVE:
                previous = self.live(name)
                if previous is not None:
                    self._move(previous, ModelStatus.RETIRED, actor, f"replaced by {version}")
            self._move(self._record(row), status, actor, reason)
            return self._record(self._row(name, version))

    def _move(self, record: ModelRecord, status: ModelStatus, actor: str, reason: str) -> None:
        now = self.clock()
        self.db.connection.execute(
            "UPDATE model_versions SET status=?, updated_at=? WHERE name=? AND version=?",
            (status.value, now.isoformat(), record.name, record.version),
        )
        self.ledger.append(
            f"model:{record.name}:{record.version}:{status.value}:{now.isoformat()}",
            "model",
            {
                "phase": "status_changed",
                "name": record.name,
                "version": record.version,
                "from": record.status.value,
                "to": status.value,
                "actor": actor,
                "reason": reason,
                "at": now.isoformat(),
            },
        )

    def get(self, name: str, version: str) -> ModelRecord | None:
        row = self._row(name, version)
        return self._record(row) if row else None

    def live(self, name: str) -> ModelRecord | None:
        row = self.db.connection.execute(
            "SELECT * FROM model_versions WHERE name=? AND status='live'", (name,)
        ).fetchone()
        return self._record(row) if row else None

    def list(self, name: str | None = None) -> list[ModelRecord]:
        rows = self.db.connection.execute(
            "SELECT * FROM model_versions WHERE (? IS NULL OR name=?) "
            "ORDER BY name, registered_at, version",
            (name, name),
        )
        return [self._record(row) for row in rows]

    def _row(self, name: str, version: str):
        return self.db.connection.execute(
            "SELECT * FROM model_versions WHERE name=? AND version=?", (name, version)
        ).fetchone()

    @staticmethod
    def _record(row) -> ModelRecord:
        return ModelRecord(
            **json.loads(row["spec"]),
            status=ModelStatus(row["status"]),
            registered_at=datetime.fromisoformat(row["registered_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
