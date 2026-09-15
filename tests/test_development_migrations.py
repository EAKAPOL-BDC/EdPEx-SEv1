"""Focused operator-runner integration tests on fresh loopback PostgreSQL databases.

Run with ``python -m unittest tests.test_development_migrations -v``. Each case uses
its own database alias and a new edpex_m1_devprep_* database, so Django test discovery
also cannot pre-apply migrations to the database under review. Set
EDPEX_KEEP_TEST_DATABASES=0 for cleanup on an unrestricted temporary CI server;
the default retains databases for restricted Windows runtimes that cannot DROP.
No application database or Supabase connection is accepted by this suite.
"""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import importlib
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class DevelopmentMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("DJANGO_DATABASE_PROFILE", "").lower() == "supabase":
            raise RuntimeError("Tests refuse the Supabase profile.")
        if os.environ.get("POSTGRES_HOST", "127.0.0.1") not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError("Tests require a loopback PostgreSQL server.")
        cls.original_settings_module = os.environ.get("DJANGO_SETTINGS_MODULE")
        os.environ["DJANGO_SETTINGS_MODULE"] = "edpex.testing"
        import django
        django.setup()
        import psycopg
        from django.db import connections
        cls.alias = "development_runner_test_" + uuid.uuid4().hex[:10]
        configuration = deepcopy(connections["default"].settings_dict)
        configuration.update({"HOST": "127.0.0.1", "ENGINE": "django.db.backends.postgresql",
            "PORT": os.environ.get("EDPEX_TEST_PORT", "55439"), "CONN_MAX_AGE": 0,
            "USER": os.environ.get("EDPEX_TEST_USER", "postgres"),
            "PASSWORD": os.environ.get("EDPEX_TEST_PASSWORD", ""), "OPTIONS": {}})
        connections.databases[cls.alias] = configuration
        cls.db = connections[cls.alias]
        cls.runner = importlib.import_module("scripts.manage_development_migrations")
        cls.commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        cls.cluster = psycopg.connect(host="127.0.0.1",
            port=os.environ.get("EDPEX_TEST_PORT", "55439"), dbname="postgres",
            user=os.environ.get("EDPEX_TEST_USER", "postgres"),
            password=os.environ.get("EDPEX_TEST_PASSWORD", ""), autocommit=True)
        cls.created = []

    @classmethod
    def tearDownClass(cls):
        from psycopg import sql
        from django.db import connections
        cls.db.close()
        keep = os.environ.get("EDPEX_KEEP_TEST_DATABASES", "1") != "0"
        if not keep:
            for name in cls.created:
                if not name.startswith("edpex_m1_devprep_") or not name.replace("_", "").isalnum():
                    raise RuntimeError("Unexpected temporary database name; refusing cleanup.")
                cls.cluster.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
        cls.cluster.close()
        del connections[cls.alias]
        del connections.databases[cls.alias]
        if cls.original_settings_module is None:
            os.environ.pop("DJANGO_SETTINGS_MODULE", None)
        else:
            os.environ["DJANGO_SETTINGS_MODULE"] = cls.original_settings_module
        print(json.dumps({"temporary_databases": cls.created, "retained": keep}))

    def setUp(self):
        from psycopg import sql
        self.name = "edpex_m1_devprep_" + uuid.uuid4().hex[:12]
        self.cluster.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.name)))
        self.created.append(self.name)
        self.db.close()
        self.db.settings_dict["OPTIONS"] = {}
        self.db.settings_dict["NAME"] = self.name
        self.db.ensure_connection()
        self.assertEqual(self.db.vendor, "postgresql")
        self.assertEqual(self.db.settings_dict["HOST"], "127.0.0.1")

    def tearDown(self):
        self.db.close()

    def run_plan(self):
        try:
            return self.runner.run(mode="plan", commit=self.commit, database=self.alias)
        finally:
            # Follow-up fixture changes use a separate session; never turn off
            # read-only inside the runner session whose behavior is under test.
            self.db.close()
            self.db.settings_dict["OPTIONS"] = {}

    def run_apply(self, plan=None, **overrides):
        plan = plan or self.run_plan()
        args = {"mode": "apply", "commit": self.commit, "database": self.alias,
                "expected_plan_hash": plan["plan_hash"],
                "backup_reference": "synthetic-local-backup-verified"}
        args.update(overrides)
        try:
            return self.runner.run(**args)
        finally:
            self.db.close()
            self.db.settings_dict["OPTIONS"] = {}

    def tables_and_rows(self):
        """Independent before/after evidence, including recorder and sentinel rows."""
        with self.db.cursor() as cursor:
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
            tables = [row[0] for row in cursor.fetchall()]
            result = {}
            for table in tables:
                cursor.execute("SELECT row_to_json(t)::text FROM " + self.db.ops.quote_name(table) + " t ORDER BY 1")
                result[table] = cursor.fetchall()
            return result

    def auth_only_fixture(self, *, initial=False, migrate=True):
        from django.contrib.auth.hashers import make_password
        from django.db.migrations.executor import MigrationExecutor
        from django.utils import timezone
        executor = MigrationExecutor(self.db)
        targets = ([("contenttypes", "0001_initial"), ("auth", "0001_initial")]
                   if initial else [node for node in executor.loader.graph.leaf_nodes()
                                    if node[0] in {"auth", "contenttypes", "admin", "sessions"}])
        if migrate:
            executor.migrate(targets)
        historical = executor.loader.project_state(targets).apps
        user_model = historical.get_model("auth", "User")
        group_model = historical.get_model("auth", "Group")
        permission_model = historical.get_model("auth", "Permission")
        ct = historical.get_model("contenttypes", "ContentType").objects.using(self.alias).create(
            app_label="development_migration_fixture", model="legacy",
            **({"name": "Synthetic historical content type"} if initial else {}))
        permission = permission_model.objects.using(self.alias).create(content_type=ct,
            codename="legacy_fixture", name="Synthetic legacy permission")
        group = group_model.objects.using(self.alias).create(name="Synthetic legacy group")
        group.permissions.add(permission)
        user = user_model.objects.using(self.alias).create(username="synthetic-legacy-user",
            password=make_password("synthetic-legacy-password"), is_active=True,
            is_staff=True, is_superuser=False, last_login=timezone.now(),
            email="synthetic-legacy-email@example.invalid")
        user.groups.add(group)
        user.user_permissions.add(permission)
        return user.pk, group.pk, permission.pk

    def assert_existing_rows_preserved(self, before):
        """Compare actual rows independently, excluding only the old CT name field."""
        after = self.tables_and_rows()
        for table in (*self.runner.AUTH_TABLES, "django_migrations"):
            old_rows = [json.loads(row[0]) for row in before[table]]
            new_rows = {row["id"]: row for row in (json.loads(item[0]) for item in after[table])}
            for row in old_rows:
                if table == "django_content_type":
                    row.pop("name", None)
                self.assertEqual(new_rows.get(row["id"]), row, table)

    def assert_no_account_values(self, output, before):
        for item in before.get("auth_user", []):
            user = json.loads(item[0])
            for field in ("username", "email", "password"):
                self.assertNotIn(user[field], output)
        self.assertNotIn("synthetic-legacy-password", output)
        self.assertNotIn("Traceback", output)

    def main_apply(self, plan, after_migrate):
        """Exercise the CLI entry point and real migrate, routing to our local alias."""
        from django.core import management
        real_run = self.runner.run
        real_command = management.call_command

        def run_local(*args, **kwargs):
            return real_run(*args, database=self.alias, **kwargs)

        def command_then_damage(*args, **kwargs):
            result = real_command(*args, **kwargs)
            after_migrate()
            return result

        stdout, stderr = StringIO(), StringIO()
        try:
            with patch.object(self.runner, "run", side_effect=run_local), \
                    patch.object(management, "call_command", side_effect=command_then_damage), \
                    patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}), \
                    redirect_stdout(stdout), redirect_stderr(stderr):
                code = self.runner.main(["--settings", "edpex.testing", "--mode", "apply",
                    "--commit", self.commit, "--expected-plan-hash", plan["plan_hash"],
                    "--backup-reference", "synthetic-local-backup-verified"])
            return code, stdout.getvalue(), stderr.getvalue()
        finally:
            self.db.close()
            self.db.settings_dict["OPTIONS"] = {}

    def test_empty_plan_has_no_recorder_and_preserves_existing_unrelated_data(self):
        with self.db.cursor() as cursor:
            cursor.execute("CREATE TABLE synthetic_existing_data (id integer PRIMARY KEY, value text)")
            cursor.execute("INSERT INTO synthetic_existing_data VALUES (1, 'keep this historical value')")
        before = self.tables_and_rows()
        self.assertNotIn("django_migrations", before)
        plan = self.run_plan()
        self.assertEqual(plan["mode"], "plan")
        self.assertEqual(plan["commit"], self.commit)
        self.assertEqual(plan["applied"], [])
        self.assertTrue(plan["pending"])
        self.assertRegex(plan["plan_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(self.tables_and_rows(), before)

    def test_existing_auth_plan_preserves_all_tables_and_migration_rows(self):
        self.auth_only_fixture()
        before = self.tables_and_rows()
        plan = self.run_plan()
        self.assertTrue(plan["applied"])
        self.assertTrue(plan["pending"])
        self.assertEqual(self.tables_and_rows(), before)
        self.assertEqual(self.run_plan()["plan_hash"], plan["plan_hash"])

    def test_plan_database_transaction_refuses_accidental_write(self):
        from django.db import DatabaseError
        from django.db.migrations.executor import MigrationExecutor
        before = self.tables_and_rows()
        observed = {}
        original = MigrationExecutor.migration_plan

        def attempt_write(executor, *args, **kwargs):
            with self.db.cursor() as cursor:
                cursor.execute("SHOW transaction_read_only")
                observed["read_only"] = cursor.fetchone()[0]
                cursor.execute("CREATE TABLE accidental_plan_write (id integer)")
            return original(executor, *args, **kwargs)

        with patch.object(MigrationExecutor, "migration_plan", attempt_write):
            with self.assertRaises(DatabaseError) as rejected:
                self.run_plan()
        self.assertEqual(observed.get("read_only"), "on")
        self.assertEqual(rejected.exception.__cause__.sqlstate, "25006")
        self.assertEqual(self.tables_and_rows(), before)

    def test_apply_empty_database_runs_real_migrations_and_post_migrate(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        from django.db.migrations.executor import MigrationExecutor
        report = self.run_apply()
        executor = MigrationExecutor(self.db)
        self.assertEqual(executor.migration_plan(executor.loader.graph.leaf_nodes()), [])
        self.assertTrue(report["no_pending_afterapply"])
        self.assertTrue(Permission.objects.using(self.alias).filter(content_type__app_label="accounts", codename="add_organization").exists())
        self.assertTrue(Permission.objects.using(self.alias).filter(content_type__app_label="auth", codename="change_user").exists())
        self.assertEqual(get_user_model().objects.using(self.alias).count(), 0)

    def test_apply_auth_upgrade_retains_identity_hash_groups_and_permissions(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        user_id, group_id, permission_id = self.auth_only_fixture()
        before = self.tables_and_rows()
        report = self.run_apply()
        after = self.tables_and_rows()
        for table in ["auth_user", "auth_group", "auth_user_groups", "auth_user_user_permissions", "auth_group_permissions"]:
            self.assertEqual(after[table], before[table], table)
        self.assertTrue(set(before["auth_permission"]).issubset(after["auth_permission"]))
        self.assertTrue(set(before["django_migrations"]).issubset(after["django_migrations"]))
        user = get_user_model().objects.using(self.alias).get(pk=user_id)
        self.assertTrue(user.check_password("synthetic-legacy-password"))
        self.assertEqual(user.groups.get().pk, group_id)
        self.assertEqual(user.user_permissions.get().pk, permission_id)
        self.assertEqual(user.groups.get().permissions.get().pk, permission_id)
        self.assertTrue(Permission.objects.using(self.alias).filter(content_type__app_label="catalog", codename="add_instrument").exists())
        self.assertTrue(report["auth_preserved"])
        self.assertTrue(report["no_pending_afterapply"])

    def test_cli_upgrades_real_initial_auth_schema_and_preserves_legacy_rows(self):
        from django.contrib.auth import get_user_model
        user_id, group_id, permission_id = self.auth_only_fixture(initial=True)
        before = self.tables_and_rows()
        self.assertEqual(len(before["django_migrations"]), 2)
        self.assertIn("name", json.loads(before["django_content_type"][0][0]))
        plan = self.run_plan()
        self.assertEqual(self.tables_and_rows(), before)
        self.assertEqual(plan["schema_exceptions"], [{
            "migration": "contenttypes.0002_remove_content_type_name",
            "table": "django_content_type", "column": "name", "operation": "remove_column",
        }])
        result = self.cli("--mode", "apply", "--expected-plan-hash", plan["plan_hash"],
                          "--backup-reference", "synthetic-local-backup-verified")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["auth_preserved"])
        self.assertTrue(report["no_pending_afterapply"])
        self.assertEqual(report["schema_exceptions"], plan["schema_exceptions"])
        self.assert_existing_rows_preserved(before)
        user = get_user_model().objects.using(self.alias).get(pk=user_id)
        self.assertTrue(user.check_password("synthetic-legacy-password"))
        self.assertEqual(user.groups.get().pk, group_id)
        self.assertEqual(user.user_permissions.get().pk, permission_id)
        self.assertEqual(user.groups.get().permissions.get().pk, permission_id)
        after_plan = self.run_plan()
        self.assertEqual(after_plan["pending"], [])
        self.assertEqual(after_plan["schema_exceptions"], [])
        self.assert_no_account_values(result.stdout + result.stderr, before)

    def test_cli_partial_failure_replans_and_resumes_from_committed_initial_auth(self):
        with self.db.cursor() as cursor:
            cursor.execute("CREATE TABLE accounts_organization (id integer PRIMARY KEY, marker text)")
            cursor.execute("INSERT INTO accounts_organization VALUES (1, 'synthetic-collision-preserved')")
        plan = self.run_plan()
        failed = self.cli("--mode", "apply", "--expected-plan-hash", plan["plan_hash"],
                          "--backup-reference", "synthetic-local-backup-verified")
        self.assertEqual(failed.returncode, 1)
        self.assertIn("Migration execution failed: migration_execution_failed.", failed.stderr)
        self.assertIn("Earlier migrations may already be committed.", failed.stderr)
        self.assertNotIn("post-apply verification failed", failed.stderr)
        partial = self.run_plan()
        self.assertEqual({(item["app"], item["name"]) for item in partial["applied"]},
                         {("contenttypes", "0001_initial"), ("auth", "0001_initial")})
        self.assertIn({"app": "accounts", "name": "0001_initial"}, partial["pending"])
        history_after_failure = self.tables_and_rows()["django_migrations"]
        with self.db.cursor() as cursor:
            cursor.execute("ALTER TABLE accounts_organization RENAME TO synthetic_collision_saved")
        self.auth_only_fixture(initial=True, migrate=False)
        before = self.tables_and_rows()
        self.assertEqual(before["django_migrations"], history_after_failure)
        resumed_plan = self.run_plan()
        self.assertNotEqual(resumed_plan["plan_hash"], plan["plan_hash"])
        resumed = self.cli("--mode", "apply", "--expected-plan-hash", resumed_plan["plan_hash"],
                           "--backup-reference", "synthetic-local-backup-verified")
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        self.assertTrue(json.loads(resumed.stdout)["auth_preserved"])
        self.assertEqual(self.run_plan()["pending"], [])
        self.assert_existing_rows_preserved(before)
        self.assertEqual(self.tables_and_rows()["synthetic_collision_saved"],
                         before["synthetic_collision_saved"])
        self.assert_no_account_values(failed.stdout + failed.stderr + resumed.stdout + resumed.stderr, before)
        self.assertNotIn("accounts_organization", failed.stderr)

    def test_verification_still_rejects_changed_data_permissions_memberships_and_history(self):
        from django.core import management
        self.auth_only_fixture(initial=True)
        self.run_apply()
        real_command = management.call_command
        cases = (
            ("auth_user", "password", "synthetic-altered-hash"),
            ("auth_user", "email", "synthetic-altered-email@example.invalid"),
            ("auth_permission", "name", "Synthetic altered permission"),
            ("auth_user_groups", None, None),
            ("auth_user_user_permissions", None, None),
            ("auth_group_permissions", None, None),
            ("django_migrations", "applied", None),
        )
        for table, column, value in cases:
            with self.subTest(table=table, column=column):
                with self.db.cursor() as cursor:
                    cursor.execute(f"SELECT * FROM {self.db.ops.quote_name(table)} ORDER BY id LIMIT 1")
                    original_row = cursor.fetchone()
                    columns = [item[0] for item in cursor.description]
                original_id = original_row[columns.index("id")]
                plan = self.run_plan()

                def mutate_after_migrate(*args, **kwargs):
                    result = real_command(*args, **kwargs)
                    with self.db.cursor() as cursor:
                        if column is None:
                            cursor.execute(f"DELETE FROM {table} WHERE id=%s", [original_id])
                        elif table == "django_migrations":
                            cursor.execute("UPDATE django_migrations SET applied=applied + interval '1 second' WHERE id=%s", [original_id])
                        else:
                            cursor.execute(f"UPDATE {table} SET {column}=%s WHERE id=%s", [value, original_id])
                    return result

                try:
                    with patch.object(management, "call_command", side_effect=mutate_after_migrate):
                        with self.assertRaises(self.runner.MigrationPreparationError) as rejected:
                            self.run_apply(plan)
                    self.assertEqual(rejected.exception.code, "legacy_auth_changed")
                    self.assertEqual(rejected.exception.phase, "verification")
                finally:
                    with self.db.cursor() as cursor:
                        if column is None:
                            projection = ", ".join(self.db.ops.quote_name(item) for item in columns)
                            placeholders = ", ".join(["%s"] * len(columns))
                            cursor.execute(f"INSERT INTO {table} ({projection}) VALUES ({placeholders})", original_row)
                        else:
                            cursor.execute(f"UPDATE {table} SET {column}=%s WHERE id=%s",
                                           [original_row[columns.index(column)], original_id])

    def test_cli_identifies_verification_failure_without_exposing_changed_account(self):
        self.auth_only_fixture(initial=True)
        before = self.tables_and_rows()

        def alter_password():
            with self.db.cursor() as cursor:
                cursor.execute("UPDATE auth_user SET password=%s", ["synthetic-altered-hash"])
            print("synthetic-altered-hash")

        code, stdout, stderr = self.main_apply(self.run_plan(), alter_password)
        self.assertEqual(code, 1)
        self.assertIn("Migrate command completed, but post-apply verification failed: legacy_auth_changed.", stderr)
        self.assertIn("Committed changes were not rolled back.", stderr)
        self.assertNotIn("Migration execution failed", stderr)
        self.assertNotIn("synthetic-altered-hash", stdout + stderr)
        self.assert_no_account_values(stdout + stderr, before)
        self.assertEqual(self.run_plan()["pending"], [])

    def test_cli_preserves_execution_failure_when_disconnection_also_breaks_unlock(self):
        from django.db import OperationalError
        self.auth_only_fixture(initial=True)
        before = self.tables_and_rows()

        def disconnect_before_command_returns():
            # Close the driver connection, leaving Django's wrapper to discover
            # the disconnect again when it attempts to release the session lock.
            self.db.connection.close()
            raise OperationalError("synthetic-transport-secret-do-not-echo")

        code, stdout, stderr = self.main_apply(self.run_plan(), disconnect_before_command_returns)
        self.assertEqual(code, 1)
        self.assertIn("Migration execution failed: migration_execution_failed.", stderr)
        self.assertNotIn("Migration preparation failed", stderr)
        self.assertNotIn("post-apply verification failed", stderr)
        self.assertNotIn("synthetic-transport-secret-do-not-echo", stdout + stderr)
        self.assert_no_account_values(stdout + stderr, before)
        self.assertIsNone(self.db.connection)
        self.assertEqual(self.run_plan()["pending"], [])
        self.assert_existing_rows_preserved(before)

    def test_approved_contenttype_removal_does_not_allow_another_missing_column(self):
        self.auth_only_fixture(initial=True)

        def drop_email():
            with self.db.cursor() as cursor:
                cursor.execute("ALTER TABLE auth_user DROP COLUMN email")

        code, _, stderr = self.main_apply(self.run_plan(), drop_email)
        self.assertEqual(code, 1)
        self.assertIn("post-apply verification failed: legacy_schema_changed.", stderr)

    def test_contenttype_name_removal_is_rejected_without_approved_pending_migration(self):
        self.auth_only_fixture()
        self.run_apply()
        with self.db.cursor() as cursor:
            cursor.execute("ALTER TABLE django_content_type ADD COLUMN name text DEFAULT 'Synthetic retained name'")
        plan = self.run_plan()
        self.assertEqual(plan["pending"], [])
        self.assertEqual(plan["schema_exceptions"], [])

        def drop_unapproved_name():
            with self.db.cursor() as cursor:
                cursor.execute("ALTER TABLE django_content_type DROP COLUMN name")

        code, _, stderr = self.main_apply(plan, drop_unapproved_name)
        self.assertEqual(code, 1)
        self.assertIn("post-apply verification failed: legacy_schema_changed.", stderr)

    def test_verification_rejects_missing_legacy_table_even_when_it_was_empty(self):
        self.run_apply()
        self.assertEqual(self.tables_and_rows()["auth_user_user_permissions"], [])

        def drop_empty_table():
            with self.db.cursor() as cursor:
                cursor.execute("DROP TABLE auth_user_user_permissions")

        code, _, stderr = self.main_apply(self.run_plan(), drop_empty_table)
        self.assertEqual(code, 1)
        self.assertIn("post-apply verification failed: legacy_schema_changed.", stderr)

    def test_schema_exception_requires_completion_and_compares_name_if_still_present(self):
        self.auth_only_fixture(initial=True)
        saved = self.runner._legacy_snapshot(self.db)
        plan = self.run_plan()
        report = self.run_apply(plan)
        with self.assertRaises(self.runner.MigrationPreparationError) as rejected:
            self.runner._verify_legacy(self.db, saved, schema_exceptions=plan["schema_exceptions"])
        self.assertEqual(rejected.exception.code, "schema_exception_not_applied")
        with self.db.cursor() as cursor:
            cursor.execute("ALTER TABLE django_content_type ADD COLUMN name text DEFAULT 'Synthetic altered name'")
        with self.assertRaises(self.runner.MigrationPreparationError) as rejected:
            self.runner._verify_legacy(self.db, saved, schema_exceptions=plan["schema_exceptions"],
                                       applied=report["applied_after"])
        self.assertEqual(rejected.exception.code, "legacy_auth_changed")

    def test_apply_refuses_stale_plan_after_database_history_changes(self):
        old_plan = self.run_plan()
        self.auth_only_fixture()
        before = self.tables_and_rows()
        self.assertNotEqual(old_plan["plan_hash"], self.run_plan()["plan_hash"])
        with self.assertRaises(self.runner.MigrationPreparationError) as rejected:
            self.run_apply(old_plan)
        self.assertEqual(rejected.exception.code, "plan_changed")
        self.assertEqual(self.tables_and_rows(), before)

    def test_plan_for_another_database_cannot_authorize_apply(self):
        from psycopg import sql
        first_plan = self.run_plan()
        other_name = "edpex_m1_devprep_" + uuid.uuid4().hex[:12]
        self.cluster.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(other_name)))
        self.created.append(other_name)
        self.db.close()
        self.db.settings_dict["NAME"] = other_name
        self.assertNotEqual(self.run_plan()["plan_hash"], first_plan["plan_hash"])
        with self.assertRaises(self.runner.MigrationPreparationError) as rejected:
            self.run_apply(first_plan)
        self.assertEqual(rejected.exception.code, "plan_changed")
        self.assertEqual(self.tables_and_rows(), {})

    def test_legacy_verification_detects_changed_values_with_unchanged_counts(self):
        user_id, _, _ = self.auth_only_fixture()
        saved = self.runner._legacy_snapshot(self.db)
        counts = self.runner._auth_counts(self.db)
        with self.db.cursor() as cursor:
            cursor.execute("UPDATE auth_user SET password=%s WHERE id=%s", ["synthetic-changed-hash", user_id])
        self.assertEqual(self.runner._auth_counts(self.db), counts)
        with self.assertRaises(self.runner.MigrationPreparationError) as rejected:
            self.runner._verify_legacy(self.db, saved)
        self.assertEqual(rejected.exception.code, "legacy_auth_changed")

    def test_apply_requires_backup_reference_and_matching_plan_hash(self):
        plan = self.run_plan()
        before = self.tables_and_rows()
        for invalid, error_code in [({"backup_reference": ""}, "apply_requires_backup"),
                ({"expected_plan_hash": ""}, "apply_requires_plan"),
                ({"expected_plan_hash": "0" * 64}, "plan_changed")]:
            with self.subTest(invalid=next(iter(invalid))):
                with self.assertRaises(self.runner.MigrationPreparationError) as rejected:
                    self.run_apply(plan, **invalid)
                self.assertEqual(rejected.exception.code, error_code)
                self.assertEqual(self.tables_and_rows(), before)

    def test_commit_must_be_full_sha_and_match_checkout(self):
        before = self.tables_and_rows()
        for commit, error_code in [("main", "invalid_commit"),
                (self.commit[:8], "invalid_commit"), ("0" * 40, "commit_mismatch")]:
            with self.subTest(commit=commit):
                with self.assertRaises(self.runner.MigrationPreparationError) as rejected:
                    self.runner.run(mode="plan", commit=commit, database=self.alias)
                self.assertEqual(rejected.exception.code, error_code)
                self.assertEqual(self.tables_and_rows(), before)

    def test_second_apply_with_current_empty_plan_preserves_all_rows(self):
        self.run_apply()
        before = self.tables_and_rows()
        plan = self.run_plan()
        self.assertEqual(plan["pending"], [])
        self.run_apply(plan)
        self.assertEqual(self.tables_and_rows(), before)

    def test_separate_connection_refuses_concurrent_apply_and_lock_releases(self):
        import psycopg
        plan = self.run_plan()
        before = self.tables_and_rows()
        with psycopg.connect(host="127.0.0.1",
                port=os.environ.get("EDPEX_TEST_PORT", "55439"), dbname=self.name,
                user=os.environ.get("EDPEX_TEST_USER", "postgres"),
                password=os.environ.get("EDPEX_TEST_PASSWORD", ""), autocommit=True) as holder:
            holder.execute("SELECT pg_advisory_lock(%s)", [self.runner.LOCK_KEY])
            holder_pid = holder.execute("SELECT pg_backend_pid()").fetchone()[0]
            with self.db.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                self.assertNotEqual(holder_pid, cursor.fetchone()[0])
            with self.assertRaises(self.runner.MigrationPreparationError) as rejected:
                self.run_apply(plan)
            self.assertEqual(rejected.exception.code, "migration_busy")
            self.assertEqual(self.tables_and_rows(), before)
        self.assertEqual(self.run_plan()["plan_hash"], plan["plan_hash"])

    def test_cli_default_is_plan_on_fresh_database(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["mode"], "plan")
        self.assertEqual(report["commit"], self.commit)
        self.assertNotIn("django_migrations", self.tables_and_rows())

    def test_cli_connection_errors_do_not_echo_connection_values(self):
        marker = "synthetic_value_do_not_echo_938475"
        result = self.cli(env_updates={"EDPEX_TEST_USER": marker,
            "EDPEX_TEST_DB_NAME": "edpex_m1_" + marker,
            "EDPEX_TEST_PASSWORD": marker, "DJANGO_SECRET_KEY": marker})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def cli(self, *args, env_updates=None):
        env = {**os.environ, "EDPEX_TEST_DB_NAME": self.name,
               **(env_updates or {})}
        return subprocess.run([sys.executable, str(ROOT / "scripts/manage_development_migrations.py"),
            "--settings", "edpex.testing", "--commit", self.commit, *args],
            cwd=ROOT, env=env, text=True, capture_output=True, timeout=60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
