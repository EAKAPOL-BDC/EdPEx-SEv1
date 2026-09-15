"""PostgreSQL invariants frozen in Django migration history."""
from django.db import migrations

FORWARD_SQL = r"""
CREATE FUNCTION edpex_audit_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Audit events are append-only' USING ERRCODE='23514';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER edpex_audit_no_changes
BEFORE UPDATE OR DELETE ON auditlog_auditevent
FOR EACH ROW EXECUTE FUNCTION edpex_audit_append_only();
"""

REVERSE_SQL = r"""DROP TRIGGER IF EXISTS edpex_audit_no_changes ON auditlog_auditevent; DROP FUNCTION IF EXISTS edpex_audit_append_only();"""

class Migration(migrations.Migration):
    dependencies = [("auditlog", "0001_initial")]
    operations = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
