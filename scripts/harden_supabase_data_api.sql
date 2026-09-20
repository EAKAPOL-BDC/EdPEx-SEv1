-- Django authorises access through its server-side PostgreSQL connection.
-- Supabase anon/authenticated clients must not read or write Django tables.
-- No business records are modified. Run as the migration owner after migration.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';
DO $$
DECLARE item record;
BEGIN
  FOR item IN
    SELECT n.nspname, c.relname, c.relkind
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relkind IN ('r','p','S')
      AND c.relname ~ '^(accounts|auditlog|auth|calculations|catalog|django|governance|leadership|participation|rounds|selfassessments|surveys)_'
  LOOP
    IF item.relkind = 'S' THEN
      EXECUTE format('REVOKE ALL PRIVILEGES ON SEQUENCE %I.%I FROM anon, authenticated, PUBLIC', item.nspname, item.relname);
    ELSE
      EXECUTE format('REVOKE ALL PRIVILEGES ON TABLE %I.%I FROM anon, authenticated, PUBLIC', item.nspname, item.relname);
    END IF;
  END LOOP;
END $$;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated, PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated, PUBLIC;
COMMIT;
