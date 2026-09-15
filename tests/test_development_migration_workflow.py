"""Exercise dispatch validation without starting Actions or contacting a database."""

from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import re
import tempfile
import textwrap
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / ".github/workflows/supabase-development-migrations.yml"
CONNECTION = ROOT / ".github/workflows/test-supabase-connection.yml"
SHA = "a" * 40
PLAN_HASH = "b" * 64
DB_SECRETS = {
    "SUPABASE_DEV_DB_HOST",
    "SUPABASE_DEV_DB_PORT",
    "SUPABASE_DEV_DB_NAME",
    "SUPABASE_DEV_DB_USER",
    "SUPABASE_DEV_DB_PASSWORD",
}


def job(workflow, name):
    """Read a two-space job block; intentionally not a general YAML parser."""
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)",
        workflow,
    )
    if match is None:
        raise AssertionError(f"Missing job: {name}")
    return match.group(1)


def validation_python(workflow):
    # Run the actual workflow code rather than a test copy of its policy.
    match = re.search(r"python - <<'PY'\n(.*?)\n          PY", job(workflow, "validate"), re.S)
    if match is None:
        raise AssertionError("Missing inline Python validation")
    return textwrap.dedent(match.group(1))


class DevelopmentMigrationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.migrations = MIGRATIONS.read_text(encoding="utf-8")
        cls.connection = CONNECTION.read_text(encoding="utf-8")

    def validate(self, workflow=None, **overrides):
        environment = {
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_SHA": SHA,
        }
        environment.update(overrides)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outputs.txt"
            environment["GITHUB_OUTPUT"] = str(output)
            stdout = StringIO()
            with patch.dict(os.environ, environment, clear=True), redirect_stdout(stdout):
                exec(compile(validation_python(workflow or self.migrations), "workflow validation", "exec"), {})
            return output.read_text(encoding="utf-8") if output.exists() else "", stdout.getvalue()

    def test_plan_is_the_default_and_pins_the_run_commit(self):
        self.assertIn("default: plan", self.migrations)
        output, _ = self.validate()
        self.assertEqual(output, f"mode=plan\ncommit_sha={SHA}\n")
        output, _ = self.validate(INPUT_MODE="plan", INPUT_COMMIT_SHA=SHA)
        self.assertEqual(output, f"mode=plan\ncommit_sha={SHA}\n")

    def test_dispatch_rejects_other_branches_tags_and_automatic_events(self):
        for context in (
            {"GITHUB_REF": "refs/heads/feature/change"},
            {"GITHUB_REF": "refs/tags/main"},
            {"GITHUB_EVENT_NAME": "push"},
            {"GITHUB_EVENT_NAME": "pull_request"},
        ):
            with self.subTest(context=context), self.assertRaises(SystemExit):
                self.validate(**context)

    def test_dispatch_rejects_arbitrary_short_and_malformed_commits(self):
        for target in ("c" * 40, SHA[:7], "$(echo injected)", SHA + "\n", "main"):
            with self.subTest(target=target), self.assertRaises(SystemExit):
                self.validate(INPUT_COMMIT_SHA=target)
        with self.assertRaises(SystemExit):
            self.validate(GITHUB_SHA="")

    def test_apply_requires_both_reviewed_plan_and_backup_reference(self):
        valid = {"INPUT_MODE": "apply", "INPUT_COMMIT_SHA": SHA, "INPUT_EXPECTED_PLAN_HASH": PLAN_HASH, "INPUT_BACKUP_REFERENCE": "dev-backup/2026-09-15-001"}
        output, _ = self.validate(**valid)
        self.assertEqual(output, f"mode=apply\ncommit_sha={SHA}\n")
        for changed in (
            {"INPUT_COMMIT_SHA": ""},
            {"INPUT_EXPECTED_PLAN_HASH": ""},
            {"INPUT_EXPECTED_PLAN_HASH": "short-hash"},
            {"INPUT_BACKUP_REFERENCE": ""},
            {"INPUT_BACKUP_REFERENCE": "a" * 121},
            {"INPUT_BACKUP_REFERENCE": "https://backup.invalid/id?token=secret"},
            {"INPUT_BACKUP_REFERENCE": "postgresql://server/database"},
            {"INPUT_BACKUP_REFERENCE": "ref\nmode=apply"},
            {"INPUT_BACKUP_REFERENCE": "$(echo injected)"},
        ):
            with self.subTest(changed=changed), self.assertRaises(SystemExit):
                self.validate(**(valid | changed))

    def test_unknown_mode_is_rejected(self):
        for mode in ("", "deploy", "APPLY"):
            with self.subTest(mode=mode), self.assertRaises(SystemExit):
                self.validate(INPUT_MODE=mode)

    def test_validation_has_no_environment_checkout_or_secrets(self):
        for workflow in (self.migrations, self.connection):
            validation = job(workflow, "validate")
            self.assertNotIn("environment:", validation)
            self.assertNotIn("secrets.", validation)
            self.assertNotIn("actions/checkout", validation)
            self.assertNotIn("${{ inputs.", validation_python(workflow))

    def test_database_jobs_are_gated_and_use_only_existing_environment_secrets(self):
        for name, command in (("plan", "--mode plan"), ("apply", "--mode apply")):
            section = job(self.migrations, name)
            with self.subTest(job=name):
                self.assertIn("needs: validate", section)
                self.assertIn(f"if: needs.validate.outputs.mode == '{name}'", section)
                self.assertIn("environment: development", section)
                self.assertIn("ref: ${{ github.sha }}", section)
                self.assertIn("persist-credentials: false", section)
                self.assertIn("DJANGO_DATABASE_PROFILE: supabase", section)
                self.assertEqual(set(re.findall(r"secrets\.([A-Z_]+)", section)), DB_SECRETS)
                self.assertIn(command, section)
                self.assertIn('--commit "$TARGET_COMMIT_SHA"', section)
                # User input is transported through env and quoted CLI arguments.
                self.assertNotRegex(section, r"run:.*\$\{\{ inputs\.")
        apply_job = job(self.migrations, "apply")
        self.assertIn('--expected-plan-hash "$EXPECTED_PLAN_HASH"', apply_job)
        self.assertIn('--backup-reference "$BACKUP_REFERENCE"', apply_job)

    def test_workflow_is_manual_only_and_has_one_non_cancelling_queue(self):
        event_header = self.migrations.split("permissions:", 1)[0]
        self.assertIn("workflow_dispatch:", event_header)
        for event in ("pull_request:", "push:", "schedule:", "workflow_run:"):
            self.assertNotIn(event, event_header)
        self.assertIn("permissions:\n  contents: read", self.migrations)
        self.assertIn("concurrency:\n  group: supabase-development-migrations\n  cancel-in-progress: false", self.migrations)
        self.assertIn("timeout-minutes:", job(self.migrations, "plan"))
        self.assertIn("timeout-minutes:", job(self.migrations, "apply"))

    def test_existing_checker_remains_select_one_and_main_only(self):
        self.validate(workflow=self.connection)
        for context in ({"GITHUB_REF": "refs/heads/feature/change"}, {"GITHUB_EVENT_NAME": "push"}):
            with self.subTest(context=context), self.assertRaises(SystemExit):
                self.validate(workflow=self.connection, **context)
        section = job(self.connection, "select-one")
        self.assertIn("needs: validate", section)
        self.assertIn("environment: development", section)
        self.assertIn("ref: ${{ github.sha }}", section)
        self.assertIn("persist-credentials: false", section)
        self.assertEqual(set(re.findall(r"secrets\.([A-Z_]+)", section)), DB_SECRETS)
        self.assertIn("run: python scripts/check_supabase_connection.py", section)
        self.assertNotIn("manage_development_migrations.py", section)


if __name__ == "__main__":
    unittest.main()
