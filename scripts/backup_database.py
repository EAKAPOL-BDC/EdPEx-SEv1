#!/usr/bin/env python3
"""Create a non-overwriting PostgreSQL archive and checksum manifest.
Uses the existing Django environment; never prints credentials or restores a DB.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New .dump archive path in a protected backup directory')
    args = parser.parse_args()
    target = args.output.resolve()
    manifest = target.with_suffix(target.suffix+'.json')
    if target.exists() or manifest.exists():
        parser.error('Output already exists; choose a new filename. Existing backups are never overwritten.')
    if not target.parent.is_dir():
        parser.error('Create a protected destination directory first.')
    executable = shutil.which('pg_dump')
    if not executable:
        parser.error('pg_dump is required; install PostgreSQL client tools and add them to PATH.')
    if (os.getenv('DJANGO_DATABASE_PROFILE', 'temporary').lower() != 'supabase'
            and not all(os.getenv(key) for key in ('POSTGRES_HOST', 'POSTGRES_DB', 'POSTGRES_USER'))):
        parser.error('Set the database profile and connection environment explicitly before creating a backup.')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'edpex.settings')
    from django.conf import settings
    db = settings.DATABASES['default']
    environment = os.environ.copy()
    environment.update(PGHOST=str(db['HOST']), PGPORT=str(db['PORT']), PGDATABASE=str(db['NAME']),
        PGUSER=str(db['USER']), PGPASSWORD=str(db['PASSWORD']), PGCONNECT_TIMEOUT='10',
        PGSSLMODE=db.get('OPTIONS',{}).get('sslmode','prefer'))
    partial = target.with_suffix(target.suffix+'.partial')
    owned_partial = False
    owned_target = False
    owned_manifest = False
    complete = False
    try:
        # Exclusive creation prevents overwriting another task's archive.
        with partial.open('xb') as output:
            owned_partial = True
            os.chmod(partial, 0o600)
            result = subprocess.run([executable, '--format=custom', '--no-password'],
                env=environment, stdout=output, stderr=subprocess.PIPE, timeout=1800)
        if result.returncode or not partial.stat().st_size:
            raise RuntimeError('Database backup failed. Check connection, permissions and pg_dump version; no archive was published.')
        digest = hashlib.sha256()
        with partial.open('rb') as data:
            for chunk in iter(lambda: data.read(1024*1024), b''): digest.update(chunk)
        metadata = {'archive':target.name, 'bytes':partial.stat().st_size, 'sha256':digest.hexdigest(),
            'created_at':datetime.now(timezone.utc).isoformat(), 'format':'postgresql-custom',
            'restore_tested':False}
        # Publish using exclusive creation, including on Windows.
        with target.open('xb') as output:
            owned_target = True
            os.chmod(target, 0o600)
            with partial.open('rb') as source:
                shutil.copyfileobj(source, output)
        with manifest.open('x',encoding='utf-8') as output:
            owned_manifest = True
            os.chmod(manifest,0o600);json.dump(metadata,output,indent=2);output.write('\n')
        complete = True
        print('Backup created:',target)
        print('Checksum manifest:',manifest)
        print('Restore has not been tested. Validate in an isolated database before relying on this backup.')
        return 0
    except (OSError, subprocess.TimeoutExpired, RuntimeError) as exc:
        print('Backup not confirmed. '+(str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__),file=sys.stderr)
        return 1
    finally:
        if owned_partial and partial.exists(): partial.unlink()
        if not complete:
            if owned_target and target.exists(): target.unlink()
            if owned_manifest and manifest.exists(): manifest.unlink()


if __name__ == '__main__':
    raise SystemExit(main())
