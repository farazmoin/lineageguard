-- Proposed change: add a new nullable column (non-destructive)
ALTER TABLE analytics.core.customers ADD COLUMN loyalty_tier VARCHAR;
