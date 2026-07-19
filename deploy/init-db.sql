-- Runs once on first postgres boot.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Append-only enforcement for the audit log (Section 3.9): after Alembic creates the
-- table, this trigger blocks UPDATE/DELETE at the database level regardless of role.
CREATE OR REPLACE FUNCTION forbid_audit_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only';
END;
$$ LANGUAGE plpgsql;

-- Deferred attachment: table may not exist yet at initdb time; attach on first migration
-- via this helper, called from a post-migrate step or manually:
--   SELECT attach_audit_guard();
CREATE OR REPLACE FUNCTION attach_audit_guard() RETURNS void AS $$
BEGIN
  IF EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'audit_log') THEN
    DROP TRIGGER IF EXISTS audit_append_only ON audit_log;
    CREATE TRIGGER audit_append_only
      BEFORE UPDATE OR DELETE ON audit_log
      FOR EACH ROW EXECUTE FUNCTION forbid_audit_mutation();
  END IF;
END;
$$ LANGUAGE plpgsql;
