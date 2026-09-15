"""Verify empty/legacy upgrades on two new, temporary PostgreSQL databases.

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


def child(mode):
    os.environ['DJANGO_SETTINGS_MODULE'] = 'edpex.testing'
    import django
    django.setup()
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from django.contrib.auth.hashers import make_password

    executor = MigrationExecutor(connection)
    if mode == 'upgrade':
        targets = [leaf for leaf in executor.loader.graph.leaf_nodes()
                   if leaf[0] in {'auth', 'contenttypes', 'admin', 'sessions'}]
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

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    from django.contrib.auth import get_user_model
    from django.conf import settings
    assert settings.AUTH_USER_MODEL == 'auth.User'
    if mode == 'upgrade':
        user = get_user_model().objects.get(username='synthetic-legacy-user')
        assert (user.pk, user.password, user.groups.get().pk, user.user_permissions.get().pk) == original
        assert user.groups.get().permissions.get().pk == original[3]
        assert user.is_active
        assert user.check_password('synthetic-legacy-password')
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM django_migrations')
            assert cursor.fetchone()[0] > legacy_migration_count
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
                      'migration_plan_empty': True, 'legacy_identity_preserved': mode == 'upgrade'}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', choices=['empty', 'upgrade'])
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
        for mode in ['empty', 'upgrade']:
            name = 'edpex_m1_' + mode + '_' + uuid.uuid4().hex[:10]
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
