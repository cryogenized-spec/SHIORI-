-- Run once on the EXISTING shiori-mcp-alpha D1 database before deploying
-- either updated Worker. New installations use schema.sql instead.
-- Legacy rows retain NULL: they cannot be replayed safely and should
-- receive IDEMPOTENCY_CONFLICT, prompting clients to choose a new key.
ALTER TABLE idempotency
  ADD COLUMN request_hash TEXT CHECK(request_hash IS NULL OR length(request_hash)=64);
