"""LineageGuard CLI — review a proposed SQL change against live DataHub metadata.

    lineageguard review --sql change.sql --platform snowflake [--max-hops 3]

Exit code is non-zero when severity is BLOCK, so it drops straight into CI.
"""
from __future__ import annotations

import argparse
import sys

from datahub.sdk import DataHubClient

from .analyze import blast_radius, parse_change, to_dataset_urn
from .review import review_change

SEV_COLOR = {"BLOCK": "\033[91m", "WARN": "\033[93m", "SAFE": "\033[92m"}
RESET = "\033[0m"


def _print_human(review: dict) -> None:
    sev = review["severity"]
    print(f"\n{SEV_COLOR.get(sev, '')}{'█' * 3} {sev}{RESET}  {review['headline']}\n")
    impact = review["_impact"]["counts"]
    print(f"  blast radius: {impact['downstream_assets']} downstream assets "
          f"({impact['dashboards']} dashboards, {impact['ml_models']} ML models, "
          f"{impact['sensitive_assets']} sensitive)")
    for label, key in [("Breaking changes", "breaking_changes"),
                       ("Sensitive-data impact", "sensitive_data_impact"),
                       ("Owners to notify", "owners_to_notify"),
                       ("Migration steps", "migration_steps")]:
        items = review.get(key) or []
        if items:
            print(f"\n  {label}:")
            for it in items:
                print(f"    • {it}")
    print(f"\n  model: {review['_model']}\n")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="lineageguard")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("review", help="Review a SQL change against DataHub")
    r.add_argument("--sql", required=True, help="Path to a .sql file with the proposed change")
    r.add_argument("--platform", default="snowflake", help="DataHub data platform (e.g. snowflake, bigquery)")
    r.add_argument("--dialect", default="snowflake", help="SQL dialect for parsing")
    r.add_argument("--env", default="PROD")
    r.add_argument("--max-hops", type=int, default=3)
    r.add_argument("--markdown", action="store_true", help="Print the PR-comment markdown instead of the human view")
    args = p.parse_args(argv)

    sql = open(args.sql).read()
    changes = parse_change(sql, dialect=args.dialect)
    if not changes:
        print("No schema/DDL change detected in the SQL.", file=sys.stderr)
        return 0

    client = DataHubClient.from_env()
    seen_assets = {}
    for c in changes:
        urn = to_dataset_urn(c.table, args.platform, args.env)
        for a in blast_radius(client, urn, max_hops=args.max_hops):
            seen_assets[a.urn] = a
    assets = list(seen_assets.values())

    review = review_change(changes, assets)
    if args.markdown:
        print(review["pr_comment_markdown"])
    else:
        _print_human(review)
    return 2 if review["severity"] == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
