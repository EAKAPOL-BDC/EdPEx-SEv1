"""Install this offline release and start LAN testing on an existing development database."""
import argparse
import os
from pathlib import Path
import sys
from nexora_web_update import install_checkout, UpdateError
from start_nexora_lan import main as start_lan, lan_ip


def main():
    home = Path(os.environ.get('USERPROFILE', str(Path.home())))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ip', required=True, type=lan_ip)
    parser.add_argument('--repo', type=Path, default=home/'EdPEx-Web'/'EdPEx-SEv1')
    parser.add_argument('--preview-root', type=Path, default=home/'EdPEx-Previews')
    parser.add_argument('--install-only', action='store_true')
    args = parser.parse_args()
    try:
        project = install_checkout(args.repo.resolve(), args.preview_root.resolve(), Path(__file__).resolve().parent)
        if args.install_only:
            print('ติดตั้งโค้ดแล้ว ยังไม่ได้เชื่อมฐานข้อมูลหรือเปิดเว็บ')
            return 0
        return start_lan(['--project', str(project), '--ip', args.ip])
    except KeyboardInterrupt:
        return 0
    except UpdateError as exc:
        print('เปิดเว็บไม่สำเร็จ: '+str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
