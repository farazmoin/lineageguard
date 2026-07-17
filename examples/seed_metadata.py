"""Seed a local DataHub with a small governed warehouse so LineageGuard has a real
lineage graph to walk: a customers table feeding an email-campaign dataset, an
exec dashboard, and a churn ML model — with owners and PII tags attached.

Run against a running quickstart:  python examples/seed_metadata.py
"""
from datahub.emitter.mce_builder import make_dataset_urn, make_tag_urn, make_user_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    DatasetPropertiesClass, GlobalTagsClass, TagAssociationClass,
    OwnershipClass, OwnerClass, OwnershipTypeClass, UpstreamClass,
    UpstreamLineageClass, DatasetLineageTypeClass,
)

GMS = "http://localhost:8080"
PLATFORM = "snowflake"


def ds(name: str) -> str:
    return make_dataset_urn(PLATFORM, name, "PROD")


def emit(emitter, urn, aspect):
    emitter.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect))


def main():
    e = DatahubRestEmitter(gms_server=GMS)

    customers = ds("analytics.core.customers")
    emails = ds("marketing.derived.email_campaigns")
    revenue = ds("analytics.derived.revenue_daily")
    churn_feat = ds("ml.features.churn_features")

    # base table with a PII tag + owner
    emit(e, customers, DatasetPropertiesClass(description="Core customer table (source of truth)."))
    emit(e, customers, GlobalTagsClass(tags=[TagAssociationClass(make_tag_urn("PII"))]))
    emit(e, customers, OwnershipClass(owners=[OwnerClass(make_user_urn("data-eng"), OwnershipTypeClass.DATAOWNER)]))

    # downstream datasets, each with lineage back to customers
    for urn, desc, owner, tags in [
        (emails, "Email campaign performance, derived from customers.", "marketing-analytics", ["PII"]),
        (revenue, "Daily revenue rollup.", "analytics", []),
        (churn_feat, "Feature table for the churn model.", "ml-team", ["PII"]),
    ]:
        emit(e, urn, DatasetPropertiesClass(description=desc))
        emit(e, urn, OwnershipClass(owners=[OwnerClass(make_user_urn(owner), OwnershipTypeClass.DATAOWNER)]))
        if tags:
            emit(e, urn, GlobalTagsClass(tags=[TagAssociationClass(make_tag_urn(t)) for t in tags]))
        emit(e, urn, UpstreamLineageClass(upstreams=[
            UpstreamClass(dataset=customers, type=DatasetLineageTypeClass.TRANSFORMED)]))

    print("Seeded DataHub with a governed warehouse (customers → 3 downstream datasets, PII-tagged).")


if __name__ == "__main__":
    main()
