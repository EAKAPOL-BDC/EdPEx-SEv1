"""Allow only the concrete migration plan shipped in the survey release."""
from django.core.management.base import BaseCommand,CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

ALLOWED={('rounds','0004_collection_data_kind'),('governance','0004_workspace_refresh'),('governance','0005_refresh_guards'),('governance','0003_accessrequest_privacy_contact_snapshot_and_more'),('governance','0001_initial'),('governance','0002_policy_guards'),('leadership','0001_initial'),('leadership','0002_register_guards'),('surveys','0003_surveyprofile_annual_target_and_more'),('surveys','0004_f04_target_guards'),('calculations','0008_activity_sources'),('calculations','0009_activity_guards'),('calculations','0007_demo_datasets'),('calculations','0006_admin_self_review'),('surveys','0001_initial'),('surveys','0002_store_guards'),('calculations','0005_anonymous_source_review'),('catalog','0004_instruction_curation_metadata')}
class Command(BaseCommand):
    help='Inspect the survey schema update; use --apply for this release only.'
    def add_arguments(self,parser):parser.add_argument('--apply',action='store_true')
    def handle(self,*args,**options):
        executor=MigrationExecutor(connection)
        targets=executor.loader.graph.leaf_nodes()
        plan=executor.migration_plan(targets)
        pending={(m.app_label,m.name) for m,backwards in plan}
        if any(backwards for m,backwards in plan) or pending-ALLOWED:
            raise CommandError('Pending migrations outside this survey release. Resolve the original project schema first; nothing was applied.')
        if not plan:
            self.stdout.write('NEXORA_SURVEY_SCHEMA_READY');return
        self.stdout.write('The allowed release migration plan is listed below. It includes the fiscal-year F04 target and eligibility register. Existing wording, approvals, users and answers are not rewritten.')
        for app,name in sorted(pending):self.stdout.write(app+'.'+name)
        if not options['apply']:
            raise CommandError('Schema update required. Read SCHEMA-UPDATE.md, then rerun the release launcher with --apply-schema.')
        executor.migrate(targets)
        self.stdout.write('NEXORA_SURVEY_SCHEMA_READY')
