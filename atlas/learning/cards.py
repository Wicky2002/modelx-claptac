"""Model cards generated from the registry, so a card cannot disagree with what is registered.

    python -m atlas.learning.cards --database data/atlas.db --out outputs/model-cards
"""

from __future__ import annotations

import argparse
from pathlib import Path

from atlas.learning.registry import ModelRecord


def model_card(record: ModelRecord) -> str:
    features = "\n".join(
        f"| `{name}` | {spec.type} | {'yes' if spec.nullable else 'no'} |"
        for name, spec in sorted(record.feature_schema.items())
    )
    datasets = "\n".join(
        f"- `{name}`: {version}" for name, version in sorted(record.dataset_versions.items())
    )
    metrics = "\n".join(f"- `{name}`: {value:g}" for name, value in sorted(record.metrics.items()))
    threshold = "none" if record.operating_threshold is None else f"{record.operating_threshold:g}"
    return f"""# {record.name} {record.version}

- **Task:** {record.task}
- **Status:** {record.status.value}
- **Operating threshold:** {threshold}
- **Weights:** {record.artifact_uri or "not recorded"}
- **Registered:** {record.registered_at.isoformat()}

## Features

| Name | Type | May be missing |
|---|---|---|
{features}

## Datasets

{datasets}

## Metrics

{metrics}

Metrics are as submitted at registration. See the training report for each number's split and seed.
"""


def main(argv=None) -> int:
    from atlas.core.storage import Database
    from atlas.learning.registry import ModelRegistry
    from atlas.memory.ledger import Ledger

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="data/atlas.db")
    parser.add_argument("--out", type=Path, default=Path("outputs/model-cards"))
    args = parser.parse_args(argv)
    db = Database(args.database)
    try:
        records = ModelRegistry(db, Ledger(db)).list()
    finally:
        db.close()
    args.out.mkdir(parents=True, exist_ok=True)
    for record in records:
        (args.out / f"{record.name}-{record.version}.md").write_text(
            model_card(record), encoding="utf-8"
        )
    print(f"Wrote {len(records)} model card(s) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
