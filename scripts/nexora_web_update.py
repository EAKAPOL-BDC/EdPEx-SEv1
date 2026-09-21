"""Install a checked offline release into an isolated worktree, then open local Django.

Use the existing project virtualenv. The survey schema is checked; only --apply-schema applies the reviewed release migrations. No seeds or account changes are run.
The release manifest and nexora-web.bundle must accompany this file in the ZIP.
"""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import warnings

RELEASE_REF = 'refs/heads/feat/nexora-anonymous-surveys'
DB_KEYS = ('SUPABASE_DEV_DB_HOST', 'SUPABASE_DEV_DB_PORT', 'SUPABASE_DEV_DB_NAME',
           'SUPABASE_DEV_DB_USER', 'SUPABASE_DEV_DB_PASSWORD')


class UpdateError(Exception):
    pass


def git(repo, *args):
    try:
        result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                                text=True, encoding='utf-8', errors='replace', check=False)
    except FileNotFoundError as exc:
        raise UpdateError('ไม่พบ Git กรุณาเปิด PowerShell ที่ใช้ Git ได้') from exc
    if result.returncode:
        raise UpdateError('Git ไม่สามารถดำเนินการได้: ' + result.stderr.strip()[:2000])
    return result.stdout.strip()


def read_release(folder):
    try:
        release = json.loads((folder / 'release.json').read_text(encoding='utf-8'))
        if not re.fullmatch(r'[0-9a-f]{40}', release['commit']):
            raise ValueError('invalid commit')
        if not re.fullmatch(r'[0-9a-f]{64}', release['bundle_sha256']):
            raise ValueError('invalid digest')
        bundle = folder / 'nexora-web.bundle'
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
        if digest != release['bundle_sha256']:
            raise UpdateError('ไฟล์ชุดอัปเดตไม่ครบหรือถูกเปลี่ยน กรุณาแตก ZIP ใหม่ทั้งชุด')
        return release, bundle
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise UpdateError('ไม่พบชุดอัปเดตที่ถูกต้อง ต้องมี release.json และ nexora-web.bundle อยู่ข้างตัวเปิด') from exc


def install_checkout(repo, preview_root, release_folder):
    release, bundle = read_release(release_folder)
    if not (repo / 'manage.py').is_file():
        raise UpdateError('ไม่พบ manage.py ในโครงการเดิม: ' + str(repo))
    git(repo, 'rev-parse', '--git-dir')
    target = preview_root / ('NEXORA-WEB-' + release['commit'][:10])
    if target.exists():
        if Path(git(target, 'rev-parse', '--show-toplevel')).resolve() != target.resolve() or not (target / 'manage.py').is_file():
            raise UpdateError('โฟลเดอร์ปลายทางนี้ไม่ใช่โครงการเว็บที่ติดตั้งไว้ กรุณาใช้ --preview-root ใหม่')
        if git(target, 'rev-parse', 'HEAD') != release['commit']:
            raise UpdateError('โฟลเดอร์รุ่นใหม่นี้มีโค้ดอื่นอยู่ กรุณาใช้ --preview-root เป็นโฟลเดอร์ใหม่')
        if git(target, 'status', '--porcelain', '--untracked-files=normal'):
            raise UpdateError('โค้ดในโฟลเดอร์รุ่นใหม่นี้มีการแก้ไข จึงหยุดเพื่อรักษางานนั้น กรุณาใช้ --preview-root ใหม่')
    else:
        print('กำลังตรวจชุดอัปเดตและสร้างโฟลเดอร์รุ่นใหม่...')
        git(repo, 'bundle', 'verify', str(bundle))
        git(repo, 'fetch', '--no-tags', str(bundle), RELEASE_REF)
        if git(repo, 'rev-parse', 'FETCH_HEAD') != release['commit']:
            raise UpdateError('รุ่นโค้ดในชุดอัปเดตไม่ตรงกับรายการที่ระบุ')
        preview_root.mkdir(parents=True, exist_ok=True)
        git(repo, 'worktree', 'add', '--detach', str(target), release['commit'])
    print('NEXORA_WEB_VERSION=' + release['commit'][:10])
    print('โฟลเดอร์เว็บ: ' + str(target))
    return target


def development_environment():
    supplied = {key: os.environ.get(key, '') for key in DB_KEYS}
    prompts = {
        'SUPABASE_DEV_DB_HOST': ('Host ของฐาน Supabase development', ''),
        'SUPABASE_DEV_DB_PORT': ('Port ของฐานข้อมูล', '5432'),
        'SUPABASE_DEV_DB_NAME': ('ชื่อฐานข้อมูล', 'postgres'),
        'SUPABASE_DEV_DB_USER': ('User ฐานข้อมูลจาก Supabase Connect (ไม่ใช่ edpexadmin)', ''),
    }
    if any(not supplied[key].strip() for key in DB_KEYS):
        print('หน้าต่างนี้ยังมีค่าฐานข้อมูลไม่ครบ กรุณากรอกค่าฐาน development เดิมที่เคยเปิดเว็บได้')
    for key, (label, default) in prompts.items():
        if not supplied[key].strip():
            supplied[key] = input(label + (f' [{default}]' if default else '') + ': ').strip() or default
        else:
            supplied[key] = supplied[key].strip()
        if not supplied[key]:
            raise UpdateError('ยังไม่ได้กรอก ' + label + ' กรุณาเปิดตัวโปรแกรมอีกครั้ง')
    if not supplied['SUPABASE_DEV_DB_PORT'].isdigit() or not 1 <= int(supplied['SUPABASE_DEV_DB_PORT']) <= 65535:
        raise UpdateError('Port ต้องเป็นตัวเลข 1–65535')
    host = supplied['SUPABASE_DEV_DB_HOST']
    if '://' in host or any(c.isspace() for c in host):
        raise UpdateError('Host ให้กรอกเฉพาะชื่อโฮสต์ ไม่ใช่ URL หรือ connection string')
    if not supplied['SUPABASE_DEV_DB_PASSWORD']:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                supplied['SUPABASE_DEV_DB_PASSWORD'] = getpass.getpass('รหัสผ่านฐานข้อมูล Supabase (ซ่อนขณะพิมพ์): ')
        except getpass.GetPassWarning as exc:
            raise UpdateError('กรุณาเรียกตัวเปิดจาก PowerShell เพื่อกรอกรหัสผ่านแบบซ่อน') from exc
        if not supplied['SUPABASE_DEV_DB_PASSWORD']:
            raise UpdateError('ยังไม่ได้กรอกรหัสผ่านฐานข้อมูล')
    # Clear other database/settings profiles only in the child environment.
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith(('PG', 'POSTGRES_', 'SUPABASE_', 'DJANGO_', 'EDPEX_TEST_'))
                   and key.upper() not in {'DATABASE_URL', 'PYTHONPATH'}}
    if os.environ.get('DJANGO_SECRET_KEY'):
        environment['DJANGO_SECRET_KEY'] = os.environ['DJANGO_SECRET_KEY']
    environment.update(supplied)
    environment.update(DJANGO_DATABASE_PROFILE='supabase', DJANGO_SETTINGS_MODULE='edpex.settings',
                       DJANGO_DEBUG='true', DJANGO_ALLOWED_HOSTS='127.0.0.1,localhost',
                       PGCONNECT_TIMEOUT='15', PYTHONUTF8='1')
    print('ใช้ฐาน development: ' + host + ':' + supplied['SUPABASE_DEV_DB_PORT'] + '/' + supplied['SUPABASE_DEV_DB_NAME'])
    return environment


def main():
    user_profile = Path(os.environ.get('USERPROFILE', str(Path.home())))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=user_profile / 'EdPEx-Web' / 'EdPEx-SEv1')
    parser.add_argument('--preview-root', type=Path, default=user_profile / 'EdPEx-Previews')
    parser.add_argument('--install-only', action='store_true', help='Install source only; do not contact any database or start the website.')
    parser.add_argument('--apply-schema', action='store_true', help='Apply only the survey migrations described in SCHEMA-UPDATE.md.')
    args = parser.parse_args()
    try:
        target = install_checkout(args.repo.resolve(), args.preview_root.resolve(), Path(__file__).resolve().parent)
        if args.install_only:
            print('ติดตั้งโค้ดเรียบร้อย ยังไม่ได้เปิดเว็บหรือเชื่อมฐานข้อมูล')
            return 0
        environment = development_environment()
        environment['PYTHONPATH'] = str(target)
        schema_command = [sys.executable, 'manage.py', 'upgrade_survey_schema']
        if args.apply_schema:
            schema_command.append('--apply')
        if subprocess.call(schema_command, cwd=target, env=environment) != 0:
            raise UpdateError('ยังเปิดเว็บรุ่นใหม่ไม่ได้ โปรดดูผลตรวจโครงสร้างฐานข้อมูลด้านบน')
        print('กำลังเปิดเว็บ เมื่อเห็น Starting development server ให้เปิด http://127.0.0.1:8000/login/')
        print('ใช้ edpexadmin และรหัสผ่านเว็บเดิม เปิดหน้าต่างนี้ค้างไว้ กด Ctrl+C เพื่อหยุดเว็บ')
        return subprocess.call([sys.executable, 'manage.py', 'runserver', '127.0.0.1:8000',
                                '--settings=edpex.settings', '--noreload'], cwd=target, env=environment)
    except KeyboardInterrupt:
        print('\nหยุดตัวเปิดเว็บแล้ว ข้อมูลเดิมยังอยู่')
        return 0
    except (UpdateError, EOFError) as exc:
        print('\nยังเปิดเว็บไม่สำเร็จ: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
