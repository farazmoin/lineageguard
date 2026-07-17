"""SQL change analysis + DataHub impact walking.

Given a proposed SQL change, work out which tables/columns it touches, then use
DataHub lineage + metadata to assemble the downstream blast radius with the
ownership and sensitivity context an agent needs to reason about risk.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

import sqlglot
from sqlglot import exp


@dataclasses.dataclass
class ChangeTarget:
    table: str  # normalized dotted name, e.g. "db.schema.table"
    columns: list[str]  # columns directly touched (dropped/altered/renamed)
    operation: str  # DROP_TABLE | DROP_COLUMN | ALTER_COLUMN | RENAME | REPLACE | UNKNOWN
    destructive: bool


def _table_name(node: exp.Table) -> str:
    parts = [p.name for p in (node.args.get("catalog"), node.args.get("db"), node.this) if p]
    return ".".join(parts)


def parse_change(sql: str, dialect: str = "snowflake") -> list[ChangeTarget]:
    """Extract the tables/columns a DDL/DML change acts on and how destructive it is."""
    targets: list[ChangeTarget] = []
    for stmt in sqlglot.parse(sql, dialect=dialect):
        if stmt is None:
            continue
        tbl = stmt.find(exp.Table)
        table = _table_name(tbl) if tbl else "?"

        if isinstance(stmt, exp.Drop):
            kind = (stmt.args.get("kind") or "TABLE").upper()
            targets.append(ChangeTarget(table, [], f"DROP_{kind}", destructive=True))
        elif isinstance(stmt, exp.Alter):
            for action in stmt.args.get("actions", []):
                if isinstance(action, exp.Drop):
                    col = action.find(exp.Column) or action.find(exp.Identifier)
                    targets.append(ChangeTarget(table, [col.name] if col else [],
                                                "DROP_COLUMN", destructive=True))
                elif isinstance(action, exp.RenameColumn):
                    cols = [c.name for c in action.find_all(exp.Column, exp.Identifier)]
                    targets.append(ChangeTarget(table, cols, "RENAME_COLUMN", destructive=True))
                elif isinstance(action, exp.AlterColumn):
                    col = action.find(exp.Column) or action.find(exp.Identifier)
                    targets.append(ChangeTarget(table, [col.name] if col else [],
                                                "ALTER_COLUMN", destructive=True))
                else:
                    targets.append(ChangeTarget(table, [], "ALTER_TABLE", destructive=False))
        elif isinstance(stmt, (exp.Create,)):
            replace = bool(stmt.args.get("replace"))
            targets.append(ChangeTarget(table, [], "REPLACE_VIEW" if replace else "CREATE",
                                        destructive=replace))
        else:
            targets.append(ChangeTarget(table, [], "UNKNOWN", destructive=False))
    return targets


# --- DataHub side ---------------------------------------------------------

@dataclasses.dataclass
class Asset:
    urn: str
    name: str
    kind: str  # dataset | dashboard | chart | mlModel | dataJob
    hops: int
    owners: list[str]
    tags: list[str]
    sensitive: bool


SENSITIVE_HINTS = ("pii", "sensitive", "gdpr", "confidential", "phi", "restricted", "personal")


def _is_sensitive(tags: list[str]) -> bool:
    return any(any(h in t.lower() for h in SENSITIVE_HINTS) for t in tags)


def to_dataset_urn(table: str, platform: str, env: str = "PROD") -> str:
    return f"urn:li:dataset:(urn:li:dataPlatform:{platform},{table},{env})"


def _read_metadata(client, urn: str) -> tuple[str, list[str], list[str]]:
    """Best-effort ownership + tag read for any entity; tolerant of entity type."""
    owners: list[str] = []
    tags: list[str] = []
    name = urn
    if "(" in urn and ")" in urn:
        inner = urn[urn.index("(") + 1: urn.rindex(")")]
        parts = inner.split(",")
        # dataset URN is (platform, NAME, ENV) → NAME is second-to-last; others fall back to last
        name = parts[-2] if len(parts) >= 3 else parts[-1]
    try:
        entity = client.entities.get(urn)
        for o in getattr(entity, "owners", None) or []:
            owners.append(str(getattr(o, "owner", o)).split(":")[-1].rstrip(")"))
        for t in getattr(entity, "tags", None) or []:
            tags.append(str(getattr(t, "tag", t)).split(":")[-1].rstrip(")"))
        if getattr(entity, "name", None):
            name = entity.name
    except Exception:
        pass
    return name, owners, tags


def blast_radius(client, source_urn: str, max_hops: int = 3) -> list[Asset]:
    """Walk downstream lineage and enrich each affected asset with owner/tag context."""
    assets: list[Asset] = []
    seen: set[str] = set()
    try:
        results = client.lineage.get_lineage(
            source_urn=source_urn, direction="downstream", max_hops=max_hops, count=500)
    except Exception:
        results = []
    for r in results:
        urn = getattr(r, "urn", None) or getattr(r, "entity", None) or str(r)
        if urn in seen:
            continue
        seen.add(urn)
        hops = getattr(r, "hops", getattr(r, "degree", 1)) or 1
        kind = "dataset"
        if ":dashboard:" in urn:
            kind = "dashboard"
        elif ":chart:" in urn:
            kind = "chart"
        elif ":mlModel" in urn:
            kind = "mlModel"
        elif ":dataJob:" in urn:
            kind = "dataJob"
        name, owners, tags = _read_metadata(client, urn)
        assets.append(Asset(urn, name, kind, hops, owners, tags, _is_sensitive(tags)))
    assets.sort(key=lambda a: (a.hops, a.kind))
    return assets
