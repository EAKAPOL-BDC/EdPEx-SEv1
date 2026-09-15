"""Verify empty, Django-auth and already-applied M1 upgrades on fresh PostgreSQL.

No migration from the checkout is run on an existing application database.
The legacy path migrates only the existing Django contrib apps, inserts a
synthetic auth user/group/permission, then upgrades through the M1 graph.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def existing_m1_fixture(apps, user):
    """Use the historical 0002 model state, never the new runtime model schema."""
    from datetime import date, timedelta
    import hashlib
    from django.utils import timezone

    now = timezone.now()
    model = apps.get_model
    org = model('accounts', 'Organization').objects.create(name='Synthetic M1 upgrade')
    scope = model('accounts', 'AccessScope').objects.create(organization=org, code='UPGRADE', name='Upgrade')
    membership = model('accounts', 'Membership').objects.create(user=user, organization=org)
    role = model('accounts', 'Role').objects.create(code='synthetic-upgrade', permissions=[
        'catalog.read', 'catalog.edit', 'translation.review', 'catalog.publish', 'round.manage'])
    model('accounts', 'RoleAssignment').objects.create(membership=membership, role=role, scope=scope)
    instrument = model('catalog', 'Instrument').objects.create(scope=scope, code='F06')
    version = model('catalog', 'InstrumentVersion').objects.create(instrument=instrument,
        version='old-m1', title_th='Synthetic old M1 self-report', assessment_method='self_report',
        instructions_curated=True)
    question = model('catalog', 'Question').objects.create(version=version,
        question_id='F06-A01', text_th='Synthetic self-report question', answer_type='integer_scale')
    instruction = model('catalog', 'InstrumentContent').objects.create(version=version,
        content_key='instruction', kind='instruction', audience='respondent', text_th='Synthetic instructions')
    bundle = model('catalog', 'TranslationBundle').objects.create(instrument_version=version, bundle_version='old-m1')
    for key, text in [(question.question_id+'.text', question.text_th), (instruction.content_key, instruction.text_th)]:
        for locale in ['th', 'en']:
            model('catalog', 'ContentTranslation').objects.create(bundle=bundle, content_key=key,
                locale=locale, text=text if locale == 'th' else 'Synthetic approved English',
                source_hash=hashlib.sha256(text.encode()).hexdigest(), status='approved',
                reviewed_by=user, reviewed_at=now)
    bundle.status, bundle.published_at = 'published', now
    bundle.save()
    version.status, version.published_at, version.checksum = 'published', now, 'a'*64
    version.save()
    label = model('catalog', 'LocalizedLabel').objects.create(scope=scope, namespace='ui', key='upgrade-label',
        version='old-m1', source_th='Synthetic label', text_en='Synthetic reviewed label',
        source_hash=hashlib.sha256(b'Synthetic label').hexdigest(), status='approved',
        reviewed_by=user, reviewed_at=now)
    label.published, label.published_at = True, now
    label.save()
    calendar = model('rounds', 'Calendar').objects.create(organization=org, scope=scope,
        code='FY', label='Synthetic fiscal calendar', calendar_type='fiscal')
    period = model('rounds', 'ReportingPeriod').objects.create(organization=org, calendar=calendar,
        code='FY2565', reporting_year_be=2565, start_date=date(2021, 10, 1), end_date=date(2022, 10, 1),
        approved=True, approved_by=user, approved_at=now)
    collection_round = model('rounds', 'CollectionRound').objects.create(organization=org, scope=scope,
        period=period, code='old-m1', owner=user, open_at=now-timedelta(hours=1),
        due_at=now+timedelta(days=1), close_at=now+timedelta(days=2), privacy_notice='Synthetic notice')
    source = model('rounds', 'DataSource').objects.create(organization=org, scope=scope,
        title='Synthetic source', location='Synthetic local fixture', source_type='raw',
        original_method='Synthetic eligibility list')
    group = model('rounds', 'RespondentGroup').objects.create(organization=org, scope=scope, code='ST1', label='Synthetic group')
    population = model('rounds', 'PopulationSnapshot').objects.create(organization=org,
        collection_round=collection_round, source=source, definition='Synthetic population',
        counting_unit='person', counts_by_group={'ST1': 1})
    model('rounds', 'PopulationMember').objects.create(organization=org, snapshot=population,
        group=group, eligible_unit_key='synthetic-old-m1-unit')
    population.status, population.frozen_at = 'frozen', now
    population.save()
    model('rounds', 'RoundInstrument').objects.create(organization=org, collection_round=collection_round,
        instrument_version=version, translation_bundle=bundle)
    collection_round.population_snapshot, collection_round.status = population, 'ready'
    collection_round.save()
    collection_round.status = 'open'
    collection_round.save()
    model('auditlog', 'AuditEvent').objects.create(organization=org, actor=user, action='synthetic.old_m1',
        object_type='rounds.CollectionRound', object_id=str(collection_round.pk),
        reason='Synthetic retained audit', metadata={'scope_id': str(scope.pk)})
    saved = {}
    for app in ['accounts', 'auditlog', 'catalog', 'rounds']:
        for historical_model in apps.get_app_config(app).get_models():
            fields = [field.attname for field in historical_model._meta.concrete_fields]
            saved[(app, historical_model._meta.model_name)] = (fields, list(historical_model.objects.order_by('pk').values_list(*fields)))
    return saved


def child(mode):
    os.environ['DJANGO_SETTINGS_MODULE'] = 'edpex.testing'
    import django
    django.setup()
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from django.contrib.auth.hashers import make_password

    executor = MigrationExecutor(connection)
    if mode in {'upgrade', 'm1-upgrade'}:
        targets = [leaf for leaf in executor.loader.graph.leaf_nodes()
                   if leaf[0] in {'auth', 'contenttypes', 'admin', 'sessions'}]
        if mode == 'm1-upgrade':
            targets += [(app, '0002_postgresql_guards') for app in ['accounts', 'auditlog', 'catalog', 'rounds']]
        executor.migrate(targets)
        legacy = executor.loader.project_state(targets).apps
        User = legacy.get_model('auth', 'User')
        Group = legacy.get_model('auth', 'Group')
        Permission = legacy.get_model('auth', 'Permission')
        ContentType = legacy.get_model('contenttypes', 'ContentType')
        content_type = ContentType.objects.create(app_label='m1_fixture', model='fixture')
        permission = Permission.objects.create(name='Synthetic legacy permission', codename='fixture', content_type=content_type)
        group = Group.objects.create(name='synthetic-legacy-group')
        group.permissions.add(permission)
        user = User.objects.create(username='synthetic-legacy-user', password=make_password('synthetic-legacy-password'), is_active=True)
        user.groups.add(group)
        user.user_permissions.add(permission)
        original = (user.pk, user.password, group.pk, permission.pk)
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM django_migrations')
            legacy_migration_count = cursor.fetchone()[0]
        if mode == 'm1-upgrade':
            original_m1 = existing_m1_fixture(legacy, user)

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    from django.contrib.auth import get_user_model
    from django.conf import settings
    assert settings.AUTH_USER_MODEL == 'auth.User'
    if mode in {'upgrade', 'm1-upgrade'}:
        user = get_user_model().objects.get(username='synthetic-legacy-user')
        assert (user.pk, user.password, user.groups.get().pk, user.user_permissions.get().pk) == original
        assert user.groups.get().permissions.get().pk == original[3]
        assert user.is_active
        assert user.check_password('synthetic-legacy-password')
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM django_migrations')
            assert cursor.fetchone()[0] > legacy_migration_count
        if mode == 'm1-upgrade':
            from django.apps import apps
            for (app, model_name), (fields, rows) in original_m1.items():
                assert list(apps.get_model(app, model_name).objects.order_by('pk').values_list(*fields)) == rows, (app, model_name)
            for model_name in ['ContentTranslation', 'LocalizedLabel']:
                assert not apps.get_model('catalog', model_name).objects.exclude(review_revision=1).exists()
    else:
        user = get_user_model().objects.create_user(username='synthetic-new-user', password='synthetic-new-password')
        assert user.check_password('synthetic-new-password')
    with connection.cursor() as cursor:
        cursor.execute('SELECT version()')
        pg_version = cursor.fetchone()[0]
    remaining = MigrationExecutor(connection).migration_plan(MigrationExecutor(connection).loader.graph.leaf_nodes())
    assert remaining == []
    print(json.dumps({'path': mode, 'database': connection.settings_dict['NAME'],
                      'postgresql': pg_version, 'auth_user_model': settings.AUTH_USER_MODEL,
                      'migration_plan_empty': True, 'legacy_identity_preserved': mode != 'empty',
                      'existing_m1_history_preserved': mode == 'm1-upgrade'}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', choices=['empty', 'upgrade', 'm1-upgrade'])
    parser.add_argument('--keep-databases', action='store_true',
                        help='Retain only the fresh test databases for a restricted local runtime; never reuse existing databases.')
    args = parser.parse_args()
    if args.child:
        child(args.child)
        return
    if os.environ.get('DJANGO_DATABASE_PROFILE', '').lower() == 'supabase':
        raise SystemExit('Refusing Supabase profile.')
    if os.environ.get('POSTGRES_HOST', '127.0.0.1') not in {'127.0.0.1', 'localhost', '::1'}:
        raise SystemExit('Refusing remote PostgreSQL host.')
    import psycopg
    from psycopg import sql
    cluster = psycopg.connect(host='127.0.0.1', port=os.environ.get('EDPEX_TEST_PORT', '55439'),
        dbname='postgres', user=os.environ.get('EDPEX_TEST_USER', 'postgres'),
        password=os.environ.get('EDPEX_TEST_PASSWORD', ''), autocommit=True)
    created = []
    try:
        for mode in ['empty', 'upgrade', 'm1-upgrade']:
            name = 'edpex_m1_' + mode.replace('-', '_') + '_' + uuid.uuid4().hex[:10]
            cluster.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            created.append(name)
            env = {**os.environ, 'EDPEX_TEST_DB_NAME': name}
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '--child', mode],
                           cwd=ROOT, env=env, check=True)
    finally:
        for name in ([] if args.keep_databases else created):
            # Only exact fresh names generated by this invocation can be dropped.
            cluster.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
        cluster.close()
        if args.keep_databases:
            print(json.dumps({'retained_temporary_databases': created}))


if __name__ == '__main__':
    main()
