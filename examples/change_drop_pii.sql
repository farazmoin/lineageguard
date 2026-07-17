-- Proposed change: drop the raw email column from the customers table
ALTER TABLE analytics.core.customers DROP COLUMN email_raw;
