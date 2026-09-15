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
# Reviewed data-loss exception: Django removes the redundant content-type
# display name; identity remains (id, app_label, model). Never infer exceptions
# from arbitrary RemoveField operations or from columns missing after apply.
SCHEMA_EXCEPTIONS = (
    {"migration": "contenttypes.0002_remove_content_type_name",
     "table": "django_content_type", "column": "name", "operation": "remove_column"},
)


class MigrationPreparationError(Exception):
    """Only static error codes may be displayed by the CLI."""

    def __init__(self, code, *, phase="preparation", diagnostics=None):
        self.code = code
        self.phase = phase
        self.diagnostics = diagnostics
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


def _autocommit_state(connection):
    return {"django_autocommit": connection.get_autocommit(),
            "driver_autocommit": connection.connection.autocommit}


def _session_state(connection):
    """Read only fixed session metadata; never return arbitrary schema names."""
    state = _autocommit_state(connection)
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT pg_catalog.current_setting('default_transaction_read_only'),
                   pg_catalog.current_setting('transaction_read_only'),
                   pg_catalog.current_setting('search_path') = 'public',
                   (SELECT setting::bigint FROM pg_catalog.pg_settings WHERE name = 'lock_timeout'),
                   (SELECT setting::bigint FROM pg_catalog.pg_settings WHERE name = 'statement_timeout')
        """)
        default_read_only, transaction_read_only, public_path, lock_ms, statement_ms = cursor.fetchone()
    state.update(
        default_transaction_read_only=default_read_only if default_read_only in {"on", "off"} else "unknown",
        transaction_read_only=transaction_read_only if transaction_read_only in {"on", "off"} else "unknown",
        search_path="public" if public_path else "other",
        lock_timeout_ms=lock_ms, statement_timeout_ms=statement_ms,
    )
    return state


def configure_connection(connection, mode):
    if connection.vendor != "postgresql" or connection.in_atomic_block:
        raise MigrationPreparationError("postgresql_session_required")
    if str(connection.settings_dict.get("PORT", "")) == "6543":
        raise MigrationPreparationError("session_connection_required")
    read_only = "on" if mode == "plan" else "off"
    expected = {"django_autocommit": True, "driver_autocommit": True,
                "default_transaction_read_only": read_only, "transaction_read_only": read_only,
                "search_path": "public", "lock_timeout_ms": 5000, "statement_timeout_ms": 900000}
    diagnostics = {"stage": "preflight", "expected": expected, "before": {}, "after": {}}
    # Never enable autocommit on a caller's active transaction: that may commit
    # pending writes. This runner owns a fresh, autocommit session instead.
    if connection.connection is not None:
        diagnostics["before"] = _autocommit_state(connection)
        if not all(diagnostics["before"].values()):
            raise MigrationPreparationError("session_autocommit_required", diagnostics=diagnostics)
    connection.close()
    options = dict(connection.settings_dict.get("OPTIONS", {}))
    existing = options.get("options", "")
    options.update({
        "connect_timeout": 10,
        "application_name": "edpex_development_migrations_" + mode,
        "options": existing + f" -c default_transaction_read_only={read_only}"
                   " -c search_path=public -c lock_timeout=5000 -c statement_timeout=900000",
    })
    connection.settings_dict["OPTIONS"] = options
    connection.settings_dict["CONN_MAX_AGE"] = 0
    connection.ensure_connection()
    try:
        diagnostics["stage"] = "startup"
        diagnostics["before"] = _autocommit_state(connection)
        if not all(diagnostics["before"].values()):
            raise MigrationPreparationError("session_autocommit_required", diagnostics=diagnostics)
        diagnostics["before"] = _session_state(connection)
        diagnostics["stage"] = "configure"
        # Startup options are an initial request, not proof of effective state.
        # Session pooling supports persistent SETs; transaction pooling does not.
        # Each statement completes in autocommit. Readback must start a NEW
        # transaction to observe default_transaction_read_only taking effect.
        with connection.cursor() as cursor:
            cursor.execute(f"SET SESSION default_transaction_read_only = {read_only}")
            cursor.execute("SET SESSION search_path = public")
            cursor.execute("SET SESSION lock_timeout = '5s'")
            cursor.execute("SET SESSION statement_timeout = '15min'")
        diagnostics["stage"] = "verify"
        diagnostics["after"] = _session_state(connection)
        actual = diagnostics["after"]
        if not actual["django_autocommit"] or not actual["driver_autocommit"]:
            raise MigrationPreparationError("session_autocommit_required", diagnostics=diagnostics)
        if any(actual[key] != read_only for key in ("default_transaction_read_only", "transaction_read_only")):
            raise MigrationPreparationError("session_mode_mismatch", diagnostics=diagnostics)
        if any(actual[key] != expected[key] for key in ("search_path", "lock_timeout_ms", "statement_timeout_ms")):
            raise MigrationPreparationError("session_settings_mismatch", diagnostics=diagnostics)
        diagnostics["stage"] = "verified"
        return diagnostics
    except MigrationPreparationError:
        raise
    except Exception:
        raise MigrationPreparationError("session_configuration_failed", diagnostics=diagnostics) from None


def inspect_plan(connection, commit):
    """Read migration graph and recorder state without ensure_schema/migrate."""
    import django
    from django.db.migrations.executor import MigrationExecutor
    from django.db.migrations.operations.fields import RemoveField

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
    schema_exceptions = []
    for migration, _ in pending:
        if (migration.app_label, migration.name) == ("contenttypes", "0002_remove_content_type_name"):
            if not any(type(operation) is RemoveField and operation.model_name == "contenttype"
                       and operation.name == "name" for operation in migration.operations):
                raise MigrationPreparationError("schema_exception_operation_mismatch")
            schema_exceptions.append(dict(SCHEMA_EXCEPTIONS[0]))
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
                   "sources": sources, "django": django.get_version(), "target": target, "identity": identity,
                   "schema_exceptions": schema_exceptions}
    return {"commit": commit, "applied": applied, "pending": planned,
            "schema_exceptions": schema_exceptions, "plan_hash": _digest(fingerprint)}


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


def _verify_legacy(connection, saved, schema_exceptions=(), applied=()):
    """Compare every old row, excluding only reviewed, completed removals.

    The caller passes exceptions from the locked, hash-checked pending plan,
    together with recorder state freshly read after migrate. Empty/default
    exceptions are strict even when contenttypes.0002 was applied in the past.
    """
    applied_names = {item["app"] + "." + item["name"] for item in applied}
    allowed = {}
    for exception in schema_exceptions:
        if exception not in SCHEMA_EXCEPTIONS or exception["migration"] not in applied_names:
            raise MigrationPreparationError("schema_exception_not_applied")
        allowed.setdefault(exception["table"], set()).add(exception["column"])
    tables = set(connection.introspection.table_names())
    with connection.cursor() as cursor:
        for table, (columns, before) in saved.items():
            if table not in tables:
                raise MigrationPreparationError("legacy_schema_changed")
            present = {item.name for item in connection.introspection.get_table_description(cursor, table)}
            missing = set(columns) - present
            if missing - allowed.get(table, set()):
                raise MigrationPreparationError("legacy_schema_changed")
            # Retain comparison of an allowed column if it is still present.
            # In particular id, account data and history are never excluded.
            retained = [index for index, column in enumerate(columns) if column not in missing]
            projection = ", ".join(connection.ops.quote_name(columns[index]) for index in retained)
            cursor.execute(f"SELECT {projection} FROM {connection.ops.quote_name(table)} ORDER BY id")
            id_index = retained.index(columns.index("id"))
            after = {row[id_index]: row for row in cursor.fetchall()}
            expected = [tuple(row[index] for index in retained) for row in before]
            if any(after.get(row[id_index]) != row for row in expected):
                raise MigrationPreparationError("legacy_auth_changed")


def run(mode, commit, expected_plan_hash="", backup_reference="", *, database="default"):
    """Run against a configured Django alias; CLI selects Supabase or loopback tests."""
    from django.core.management import call_command
    from django.db import connections

    validate_request(mode, commit, expected_plan_hash, backup_reference)
    connection = connections[database]
    locked = False
    phase = "preparation"
    try:
        session_diagnostics = configure_connection(connection, mode)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [LOCK_KEY])
            locked = cursor.fetchone()[0]
        if not locked:
            raise MigrationPreparationError("migration_busy")
        report = {"mode": mode, "session_diagnostics": session_diagnostics, **inspect_plan(connection, commit),
                  "auth_before": _auth_counts(connection)}
        if mode == "plan":
            return report
        if report["plan_hash"] != expected_plan_hash:
            raise MigrationPreparationError("plan_changed")
        saved = _legacy_snapshot(connection)
        # Suppress driver, migration and hook output. The only displayed output
        # is the allowlisted report below; never raw exception/SQL/account data.
        sink = io.StringIO()
        phase = "migration"
        try:
            with redirect_stdout(sink), redirect_stderr(sink):
                call_command("migrate", database=database, interactive=False, verbosity=0,
                             stdout=sink, stderr=sink)
        except Exception:
            raise MigrationPreparationError("migration_execution_failed", phase="migration") from None
        phase = "verification"
        try:
            after = inspect_plan(connection, commit)
            if after["pending"]:
                raise MigrationPreparationError("migrations_still_pending")
            _verify_legacy(connection, saved, report["schema_exceptions"], after["applied"])
            auth_after = _auth_counts(connection)
        except MigrationPreparationError as error:
            raise MigrationPreparationError(error.code, phase="verification") from None
        except Exception:
            raise MigrationPreparationError("post_apply_verification_error", phase="verification") from None
        report.update(auth_preserved=True, auth_after=auth_after,
                      no_pending_afterapply=True, applied_after=after["applied"])
        return report
    finally:
        # A disconnected session can fail to unlock as well as fail to migrate.
        # Cleanup must not replace the original safe failure stage/message.
        already_failing = sys.exc_info()[0] is not None
        try:
            try:
                if locked and connection.connection is not None:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_KEY])
            finally:
                connection.close()
        except Exception:
            if not already_failing:
                raise MigrationPreparationError("connection_cleanup_failed", phase=phase) from None


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
    lines += ["", "Reviewed schema exceptions (only for the pending plan above):"]
    for exception in report["schema_exceptions"]:
        lines.append(f"- `{exception['migration']}`: {exception['operation']} "
                     f"`{exception['table']}.{exception['column']}`.")
    if not report["schema_exceptions"]:
        lines.append("None.")
    if report["mode"] == "apply":
        lines += ["", "Apply completed; no pending migrations. Existing Django account, group,",
                  "permission and migration-history rows preserved."]
    else:
        lines += ["", "Read-only plan. No migrations or database records were written."]
    lines += ["", "Auth counts (no usernames, passwords or connection details):",
              "```json", json.dumps(report.get("auth_after", report["auth_before"]), indent=2), "```", ""]
    lines += ["Session diagnostics (fixed metadata only):", "```json",
              json.dumps(report["session_diagnostics"], indent=2), "```", ""]
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
        if error.phase == "migration":
            message = ("Migration execution failed: " + error.code + ". "
                       "Earlier migrations may already be committed.")
        elif error.phase == "verification":
            message = ("Migrate command completed, but post-apply verification failed: " + error.code + ". "
                       "Committed changes were not rolled back.")
        else:
            message = "Migration preparation failed: " + error.code + "."
        print(message, file=sys.stderr)
        if error.diagnostics is not None:
            print(json.dumps({"session_diagnostics": error.diagnostics}), file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Migration preparation failed ({type(error).__name__}); connection details omitted.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
