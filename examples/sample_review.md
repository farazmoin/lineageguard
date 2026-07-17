## 🚫 LineageGuard: BLOCK

**Change:** `DROP COLUMN analytics.core.customers.email_raw` (destructive)

**Blast radius (from DataHub):** 3 downstream datasets, 2 PII-tagged.

| Downstream asset | Hops | Owner | Sensitive |
|---|---|---|---|
| `marketing.derived.email_campaigns` | 1 | marketing-analytics | ⚠️ PII |
| `ml.features.churn_features` | 1 | ml-team | ⚠️ PII |
| `analytics.derived.revenue_daily` | 1 | analytics | — |

**Why blocked:** Destructive drop of a column feeding 3 direct consumers, including two PII pipelines, with no migration path in this PR.

**Required sign-offs:** @marketing-analytics, @ml-team, @analytics

**Path to merge:**
1. Owner sign-offs for all 3 assets.
2. Agree replacement (e.g., hashed email) if data still needed.
3. Migrate all 3 downstream consumers off `email_raw`.
4. Deprecate column in DataHub and confirm zero usage.
5. Re-run LineageGuard with empty blast radius, then drop.
