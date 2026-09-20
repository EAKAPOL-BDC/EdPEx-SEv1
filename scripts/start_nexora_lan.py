"""Start an installed NEXORA development checkout on a specific private LAN IPv4.

No installation, migrations, firewall changes or credential files are created.
"""
import argparse
import getpass
import ipaddress
import os
from pathlib import Path
import subprocess
import sys
import warnings


class LaunchError(Exception):
    pass


def lan_ip(value):
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise argparse.ArgumentTypeError('LAN IP ต้องเป็น IPv4 เช่น 10.51.72.130') from exc
    networks = ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')
    if not any(address in ipaddress.IPv4Network(n) for n in networks):
        raise argparse.ArgumentTypeError('ตัวเปิดนี้รับเฉพาะ IP ภายในเครือข่ายส่วนตัว')
    return str(address)


def environment(project, address):
    if os.environ.get('NEXORA_ENVIRONMENT', 'development').lower() != 'development':
        raise LaunchError('ตัวเปิดนี้ใช้กับ development เท่านั้น ไม่เปลี่ยนค่าระบบ production')
    if os.environ.get('NEXORA_TRUST_HTTPS_PROXY') == 'true':
        raise LaunchError('พบการตั้งค่า HTTPS proxy กรุณาใช้ตัวเปิดสำหรับสภาพแวดล้อมนั้น')
    prompts = (
        ('SUPABASE_DEV_DB_HOST', 'Host ฐาน Supabase development เดิม (ไม่ใช่ IP เครื่อง Windows)', ''),
        ('SUPABASE_DEV_DB_PORT', 'Port ฐานข้อมูลตามการเชื่อมต่อเดิม', '5432'),
        ('SUPABASE_DEV_DB_NAME', 'ชื่อฐานข้อมูล', 'postgres'),
        ('SUPABASE_DEV_DB_USER', 'User ฐานข้อมูล (ไม่ใช่ edpexadmin)', ''),
    )
    supplied = {}
    for key, label, default in prompts:
        value = os.environ.get(key, '').strip()
        if not value:
            value = input(label + (f' [{default}]' if default else '') + ': ').strip() or default
        if not value:
            raise LaunchError('ยังไม่ได้กรอก ' + label)
        supplied[key] = value
    host = supplied['SUPABASE_DEV_DB_HOST']
    if '://' in host or any(c.isspace() for c in host) or any(c in host for c in '/:@'):
        raise LaunchError('Host ต้องเป็นชื่อโฮสต์อย่างเดียว ไม่ใช่ URL หรือ connection string')
    port = supplied['SUPABASE_DEV_DB_PORT']
    if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise LaunchError('Port ฐานข้อมูลต้องเป็นตัวเลข 1–65535')
    password = os.environ.get('SUPABASE_DEV_DB_PASSWORD', '')
    if not password:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                password = getpass.getpass('รหัสผ่านฐานข้อมูล Supabase (ซ่อนขณะพิมพ์): ')
        except getpass.GetPassWarning as exc:
            raise LaunchError('ไม่สามารถซ่อนรหัสผ่านได้ กรุณาเปิดจาก PowerShell โดยตรง') from exc
    if not password:
        raise LaunchError('ยังไม่ได้กรอกรหัสผ่านฐานข้อมูล')
    supplied['SUPABASE_DEV_DB_PASSWORD'] = password
    result = {k: v for k, v in os.environ.items()
              if not k.upper().startswith(('PG', 'POSTGRES_', 'SUPABASE_', 'DJANGO_', 'EDPEX_TEST_'))
              and k.upper() not in {'DATABASE_URL', 'PYTHONPATH'}}
    if os.environ.get('DJANGO_SECRET_KEY'):
        result['DJANGO_SECRET_KEY'] = os.environ['DJANGO_SECRET_KEY']
    result.update(supplied)
    result.update(DJANGO_DATABASE_PROFILE='supabase', DJANGO_SETTINGS_MODULE='edpex.settings',
                  DJANGO_DEBUG='true', DJANGO_ALLOWED_HOSTS=f'localhost,127.0.0.1,{address}',
                  PYTHONPATH=str(project), PYTHONUTF8='1', PGCONNECT_TIMEOUT='15')
    return result


def main(argv=None):
    profile = Path(os.environ.get('USERPROFILE', str(Path.home())))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=profile / 'EdPEx-Previews' / 'NEXORA-WEB-c975590a70')
    parser.add_argument('--ip', type=lan_ip, required=True)
    args = parser.parse_args(argv)
    project = args.project.resolve()
    try:
        if not (project / 'manage.py').is_file() or not (project / 'edpex/settings.py').is_file():
            raise LaunchError('ไม่พบโครงการ NEXORA ที่ ' + str(project) + ' ใช้ --project ระบุโฟลเดอร์ที่ติดตั้งไว้')
        print('โฟลเดอร์เว็บ: ' + str(project))
        print('ใช้ข้อมูลเชื่อมต่อ development เดิม กรอกทีละช่องแล้วกด Enter')
        child_env = environment(project, args.ip)
        print(f'เมื่อเห็น Starting development server เปิด http://{args.ip}:8000/workspace/')
        print('เปิดหน้าต่างนี้ค้างไว้ กด Ctrl+C เพื่อหยุด | /survey/ ผ่าน LAN ยังต้องใช้ HTTPS')
        return subprocess.call([sys.executable, str(project / 'manage.py'), 'runserver',
                                f'{args.ip}:8000', '--settings=edpex.settings', '--noreload'],
                               cwd=project, env=child_env)
    except KeyboardInterrupt:
        print('\nหยุดตัวเปิดเว็บแล้ว')
        return 0
    except (LaunchError, EOFError, OSError) as exc:
        print('ยังเปิดเว็บไม่สำเร็จ: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
