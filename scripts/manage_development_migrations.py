"""Explicit, commit-bound Django migration plan/apply for development.

Plan never calls migrate or creates django_migrations. PostgreSQL enforces a
read-only session; apply uses the same session advisory lock and rechecks the
reviewed plan before running Django's normal migrate command/post_migrate hooks.
Connection details and legacy account values are never part of the report.
"""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import inspect
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCK_KEY = 0x45445045584D31
AUTH_TABLES = (
    "auth_user", "auth_group", "auth_permission", "auth_user_groups",
    "auth_user_user_permissions", "auth_group_permissions", "django_content_type",
)


class MigrationPreparationError(Exception):
    """Only static error codes may be displayed by the CLI."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str,
                                     separators=(",", ":")).encode()).hexdigest()


def validate_request(mode, commit, expected_plan_hash, backup_reference):
    if mode not in {"plan", "apply"}:
        raise MigrationPreparationError("invalid_mode")
    if not re.fullmatch(r"[0-9a-f]{40}", commit or ""):
        raise MigrationPreparationError("invalid_commit")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                   stderr=subprocess.DEVNULL, text=True).strip()
    if head != commit:
        raise MigrationPreparationError("commit_mismatch")
    if mode == "apply":
        if not re.fullmatch(r"[0-9a-f]{64}", expected_plan_hash or ""):
            raise MigrationPreparationError("apply_requires_plan")
        # A non-secret ticket/reference, not a URL, credential or backup content.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,119}", backup_reference or ""):
            raise MigrationPreparationError("apply_requires_backup")


def configure_connection(connection, mode):
    if connection.vendor != "postgresql" or connection.in_atomic_block:
        raise MigrationPreparationError("postgresql_session_required")
    if str(connection.settings_dict.get("PORT", "")) == "6543":
        raise MigrationPreparationError("session_connection_required")
    connection.close()
    options = dict(connection.settings_dict.get("OPTIONS", {}))
    existing = options.get("options", "")
    read_only = "on" if mode == "plan" else "off"
    options.update({
        "connect_timeout": 10,
        "application_name": "edpex_development_migrations_" + mode,
        "options": existing + f" -c default_transaction_read_only={read_only}"
                   " -c search_path=public -c lock_timeout=5000 -c statement_timeout=900000",
    })
    connection.settings_dict["OPTIONS"] = options
    connection.settings_dict["CONN_MAX_AGE"] = 0
    connection.ensure_connection()
    with connection.cursor() as cursor:
        cursor.execute("SHOW transaction_read_only")
        if cursor.fetchone()[0] != read_only:
            raise MigrationPreparationError("session_mode_mismatch")


def inspect_plan(connection, commit):
    """Read migration graph and recorder state without ensure_schema/migrate."""
    import django
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    loader = executor.loader
    loader.check_consistent_history(connection)
    if loader.detect_conflicts():
        raise MigrationPreparationError("migration_conflict")
    if set(loader.applied_migrations) - set(loader.disk_migrations):
        raise MigrationPreparationError("unknown_applied_migration")
    pending = executor.migration_plan(loader.graph.leaf_nodes())
    if any(backwards for _, backwards in pending):
        raise MigrationPreparationError("backward_migration_forbidden")
    applied = [{"app": app, "name": name} for app, name in sorted(loader.applied_migrations)]
    planned = [{"app": migration.app_label, "name": migration.name} for migration, _ in pending]
    sources = {}
    for key, migration in sorted(loader.disk_migrations.items()):
        path = inspect.getsourcefile(type(migration))
        if path is None:
            raise MigrationPreparationError("migration_source_unavailable")
        sources[".".join(key)] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_user, current_schema()")
        identity = cursor.fetchone()
    # Identity prevents applying a plan to another endpoint/database/role. It is
    # incorporated in the final digest only, never emitted as a report field.
    target = [connection.settings_dict.get(key) for key in ("HOST", "PORT", "NAME", "USER")]
    history = [(app, name, record.applied) for (app, name), record in sorted(loader.applied_migrations.items())]
    fingerprint = {"commit": commit, "applied": history, "pending": planned,
                   "sources": sources, "django": django.get_version(), "target": target, "identity": identity}
    return {"commit": commit, "applied": applied, "pending": planned, "plan_hash": _digest(fingerprint)}


def _auth_counts(connection):
    tables = set(connection.introspection.table_names())
    counts = {}
    with connection.cursor() as cursor:
        for table in AUTH_TABLES:
            if table in tables:
                cursor.execute(f"SELECT count(*) FROM {connection.ops.quote_name(table)}")
                counts[table] = cursor.fetchone()[0]
            else:
                counts[table] = 0
    return counts


def _legacy_snapshot(connection):
    """Old account/history rows stay in process memory, never in logs/artifacts."""
    tables = set(connection.introspection.table_names())
    saved = {}
    with connection.cursor() as cursor:
        for table in (*AUTH_TABLES, "django_migrations"):
            if table not in tables:
                continue
            cursor.execute(f"SELECT * FROM {connection.ops.quote_name(table)} ORDER BY id")
            columns = [item[0] for item in cursor.description]
            saved[table] = (columns, cursor.fetchall())
    return saved


def _verify_legacy(connection, saved):
    with connection.cursor() as cursor:
        for table, (columns, before) in saved.items():
            projection = ", ".join(connection.ops.quote_name(column) for column in columns)
            cursor.execute(f"SELECT {projection} FROM {connection.ops.quote_name(table)} ORDER BY id")
            id_index = columns.index("id")
            after = {row[id_index]: row for row in cursor.fetchall()}
            if any(after.get(row[id_index]) != row for row in before):
                raise MigrationPreparationError("legacy_auth_changed")


def run(mode, commit, expected_plan_hash="", backup_reference="", *, database="default"):
    """Run against a configured Django alias; CLI selects Supabase or loopback tests."""
    from django.core.management import call_command
    from django.db import connections

    validate_request(mode, commit, expected_plan_hash, backup_reference)
    connection = connections[database]
    locked = False
    try:
        configure_connection(connection, mode)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_KEY])
            locked = cursor.fetchone()[0]
        if not locked:
            raise MigrationPreparationError("migration_busy")
        report = {"mode": mode, **inspect_plan(connection, commit),
                  "auth_before": _auth_counts(connection)}
        if mode == "plan":
            return report
        if report["plan_hash"] != expected_plan_hash:
            raise MigrationPreparationError("plan_changed")
        saved = _legacy_snapshot(connection)
        # Suppress driver, migration and hook output. The only displayed output
        # is the allowlisted report below; never raw exception/SQL/account data.
        sink = io.StringIO()
        with redirect_stdout(sink), redirect_stderr(sink):
            call_command("migrate", database=database, interactive=False, verbosity=0,
                         stdout=sink, stderr=sink)
        _verify_legacy(connection, saved)
        after = inspect_plan(connection, commit)
        if after["pending"]:
            raise MigrationPreparationError("migrations_still_pending")
        report.update(auth_preserved=True, auth_after=_auth_counts(connection),
                      no_pending_afterapply=True, applied_after=after["applied"])
        return report
    finally:
        try:
            if locked and connection.connection is not None:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_KEY])
        finally:
            connection.close()


def _display(report):
    print(json.dumps(report, indent=2))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary:
        return
    lines = ["## Django migrations: " + report["mode"], "",
             "Commit: `" + report["commit"] + "`", "",
             "Plan hash: `" + report["plan_hash"] + "`", "",
             "| Status | Migration |", "| --- | --- |"]
    for status, key in [("Applied", "applied"), ("Pending", "pending")]:
        for item in report[key]:
            lines.append(f"| {status} | `{item['app']}.{item['name']}` |")
    if not report["pending"]:
        lines += ["", "No pending migrations."]
    if report["mode"] == "apply":
        lines += ["", "Apply completed; no pending migrations. Existing Django account, group,",
                  "permission and migration-history rows preserved."]
    else:
        lines += ["", "Read-only plan. No migrations or database records were written."]
    lines += ["", "Auth counts (no usernames, passwords or connection details):",
              "```json", json.dumps(report.get("auth_after", report["auth_before"]), indent=2), "```", ""]
    with open(summary, "a", encoding="utf-8") as stream:
        stream.write("\n".join(lines))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["plan", "apply"], default="plan")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--expected-plan-hash", default="")
    parser.add_argument("--backup-reference", default="")
    parser.add_argument("--settings", choices=["edpex.settings", "edpex.testing"], default="edpex.settings")
    args = parser.parse_args(argv)
    try:
        # Validate before loading settings or attempting any database connection.
        validate_request(args.mode, args.commit, args.expected_plan_hash, args.backup_reference)
        if args.settings == "edpex.settings" and os.environ.get("DJANGO_DATABASE_PROFILE", "").lower() != "supabase":
            raise MigrationPreparationError("supabase_development_profile_required")
        sys.path.insert(0, str(ROOT))
        os.environ["DJANGO_SETTINGS_MODULE"] = args.settings
        import django
        django.setup()
        report = run(args.mode, args.commit, args.expected_plan_hash, args.backup_reference)
        _display(report)
    except MigrationPreparationError as error:
        print("Migration preparation failed: " + error.code + ".", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Migration preparation failed ({type(error).__name__}); connection details omitted.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
