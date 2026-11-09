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


# Moves that need no approval. Changing which version is live happens only in promote() and rollback().
TRANSITIONS: dict[ModelStatus, set[ModelStatus]] = {
    ModelStatus.CANDIDATE: {ModelStatus.SHADOW, ModelStatus.RETIRED},
    ModelStatus.SHADOW: {ModelStatus.RETIRED},
    ModelStatus.LIVE: set(),
    ModelStatus.RETIRED: set(),
}


def promotion_key(name: str, version: str) -> str:
    return f"promote:{name}:{version}"


def rollback_key(name: str, current: str, target: str) -> str:
    return f"rollback:{name}:{current}:{target}"


class RegistryError(ValueError):
    """A registration or status change the registry refuses."""


class FeatureSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["float", "int", "str", "bool"]
    # Missing data must stay distinguishable from zero (proposal §5.2), so a feature that may be
    # missing says so and arrives as None rather than as a filled-in default.
    nullable: bool = False


class FeatureStats(BaseModel):
    """A numeric feature's training distribution, which drift checks compare against."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    mean: float = Field(allow_inf_nan=False)
    std: float = Field(gt=0, allow_inf_nan=False)
    missing_rate: float = Field(default=0.0, ge=0, le=1)


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
    feature_stats: dict[str, FeatureStats] = Field(default_factory=dict)


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
            CREATE TABLE IF NOT EXISTS model_rollback (
                name TEXT PRIMARY KEY, live TEXT NOT NULL, previous TEXT NOT NULL);
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
        """Make a move that needs no approval. No route to or from live goes through here."""
        with self.db.transaction():
            row = self._row(name, version)
            if row is None:
                raise RegistryError(f"unknown model {name} {version}")
            current = ModelStatus(row["status"])
            if status not in TRANSITIONS[current]:
                raise RegistryError(f"{name} {version}: {current.value} -> {status.value} refused")
            self._move(self._record(row), status, actor, reason)
            return self._record(self._row(name, version))

    def promote(self, name: str, version: str, *, actor: str) -> ModelRecord:
        """Make a shadow version live, only if a human approved exactly this version."""
        with self.db.transaction():
            row = self._row(name, version)
            if row is None or ModelStatus(row["status"]) is not ModelStatus.SHADOW:
                raise RegistryError(f"{name} {version} is not in shadow")
            self._require_approval(promotion_key(name, version))
            previous = self.live(name)
            if previous is not None:
                self._move(previous, ModelStatus.RETIRED, actor, f"replaced by {version}")
                self.db.connection.execute(
                    "INSERT OR REPLACE INTO model_rollback VALUES (?,?,?)",
                    (name, version, previous.version),
                )
            else:
                self.db.connection.execute("DELETE FROM model_rollback WHERE name=?", (name,))
            self._move(self._record(row), ModelStatus.LIVE, actor, "approved promotion")
            return self._record(self._row(name, version))

    def rollback_target(self, name: str) -> str | None:
        """The version a one-step rollback would restore, if there is one."""
        current = self.live(name)
        row = self.db.connection.execute(
            "SELECT previous FROM model_rollback WHERE name=? AND live=?",
            (name, current.version if current else ""),
        ).fetchone()
        return row["previous"] if row else None

    def rollback(self, name: str, *, actor: str) -> ModelRecord:
        """Restore the version the last promotion replaced. One step only, with human approval."""
        with self.db.transaction():
            current, target = self.live(name), self.rollback_target(name)
            if current is None or target is None:
                raise RegistryError(f"{name} has nothing to roll back to")
            self._require_approval(rollback_key(name, current.version, target))
            self._move(current, ModelStatus.RETIRED, actor, f"rolled back to {target}")
            self._move(self.get(name, target), ModelStatus.LIVE, actor, "approved rollback")
            self.db.connection.execute("DELETE FROM model_rollback WHERE name=?", (name,))
            return self.get(name, target)

    def _require_approval(self, key: str) -> None:
        # The Gateway writes these two phases only when a person approves. A low-consequence
        # authorisation has neither, so loosening the policy alone cannot make a model live.
        if not any(self.ledger.get(f"action:{key}:{phase}") for phase in ("approved", "edited")):
            raise RegistryError(f"no human approval on record for {key}")

    def _move(self, record: ModelRecord, status: ModelStatus, actor: str, reason: str) -> None:
        now = self.clock()
        self.db.connection.execute(
            "UPDATE model_versions SET status=?, updated_at=? WHERE name=? AND version=?",
            (status.value, now.isoformat(), record.name, record.version),
        )
        self.ledger.append(
            f"model:{record.name}:{record.version}:{record.status.value}>{status.value}"
            f":{now.isoformat()}",
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
