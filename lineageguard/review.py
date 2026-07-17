"""The agent brain: turn a change + its DataHub blast radius into a risk review.

Claude (Fable 5 by default) receives the structured impact graph and produces a
PR-comment-style review: severity, what breaks, who to notify, data-sensitivity
warnings, and concrete migration steps. The model never guesses lineage — every
downstream asset, owner, and tag is supplied from DataHub, so the reasoning is
grounded in real metadata.
"""
from __future__ import annotations

import json
import os
from typing import Optional

import anthropic

from .analyze import Asset, ChangeTarget

MODEL = os.environ.get("LINEAGEGUARD_MODEL", "claude-fable-5")
FALLBACK_MODEL = "claude-opus-4-8"

SYSTEM = """You are LineageGuard, a data-platform change reviewer. You are given a \
proposed SQL/schema change and the EXACT downstream blast radius from a DataHub \
metadata graph (every affected table, dashboard, ML model, its owners, and its \
sensitivity tags). Your job is to protect the data platform.

Rules:
- Reason only from the supplied metadata. Never invent downstream assets, owners, or tags.
- Assess severity as one of: BLOCK (destructive change with downstream consumers or \
sensitive data and no migration path), WARN (real downstream impact that needs \
coordination), or SAFE (no meaningful downstream impact).
- Call out sensitive-data exposure explicitly and separately.
- Name the specific owners who must sign off, by asset.
- Give concrete, ordered migration steps a data engineer can follow.
Be precise and terse. This is a PR review, not an essay."""

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "severity": {"type": "string", "enum": ["BLOCK", "WARN", "SAFE"]},
        "headline": {"type": "string"},
        "breaking_changes": {"type": "array", "items": {"type": "string"}},
        "sensitive_data_impact": {"type": "array", "items": {"type": "string"}},
        "owners_to_notify": {"type": "array", "items": {"type": "string"}},
        "migration_steps": {"type": "array", "items": {"type": "string"}},
        "pr_comment_markdown": {"type": "string"},
    },
    "required": ["severity", "headline", "breaking_changes", "sensitive_data_impact",
                 "owners_to_notify", "migration_steps", "pr_comment_markdown"],
    "additionalProperties": False,
}


def _impact_payload(changes: list[ChangeTarget], assets: list[Asset]) -> dict:
    return {
        "proposed_change": [
            {"table": c.table, "columns": c.columns, "operation": c.operation,
             "destructive": c.destructive} for c in changes],
        "downstream_blast_radius": [
            {"asset": a.name, "type": a.kind, "hops_downstream": a.hops,
             "owners": a.owners, "tags": a.tags, "sensitive": a.sensitive}
            for a in assets],
        "counts": {
            "downstream_assets": len(assets),
            "sensitive_assets": sum(1 for a in assets if a.sensitive),
            "dashboards": sum(1 for a in assets if a.kind == "dashboard"),
            "ml_models": sum(1 for a in assets if a.kind == "mlModel"),
        },
    }


def review_change(changes: list[ChangeTarget], assets: list[Asset],
                  client: Optional[anthropic.Anthropic] = None) -> dict:
    client = client or anthropic.Anthropic()
    payload = _impact_payload(changes, assets)
    user = (
        "Review this proposed data-platform change. The blast radius below is the "
        "ground truth from DataHub — reason only from it.\n\n"
        + json.dumps(payload, indent=2)
    )
    kwargs = dict(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": REVIEW_SCHEMA}},
    )
    try:
        resp = client.beta.messages.create(
            betas=["server-side-fallback-2026-06-01"],
            fallbacks=[{"model": FALLBACK_MODEL}], **kwargs)
    except Exception:
        # older SDK / model without server-side fallback: plain call
        resp = client.messages.create(**kwargs)
    text = next((b.text for b in resp.content if b.type == "text"), "{}")
    review = json.loads(text)
    review["_impact"] = payload
    review["_model"] = getattr(resp, "model", MODEL)
    return review
