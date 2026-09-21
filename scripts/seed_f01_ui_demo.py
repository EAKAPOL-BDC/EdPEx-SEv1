"""One-time synthetic fixture, only in dedicated empty development DB."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['DJANGO_SETTINGS_MODULE']='edpex.participation_demo'
import django
django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from tests.test_surveys import setup_surveys
from apps.participation.services import configure_policy

with transaction.atomic():
    if get_user_model().objects.exists():
        raise RuntimeError('Refusing to seed a non-empty development database.')
    fixture=setup_surveys(only={'F01'},data_kind='synthetic')
    configure_policy(fixture.actor,fixture.selected['F01'].pk,activity_code='f01-ui-demo',
                     label_th='เข้าร่วมแบบประเมิน F01 · ทดสอบ',label_en='F01 participation · test',
                     expires_at=timezone.now()+timedelta(days=30),workload=True,prize=True)
print('Synthetic F01 development collection ready; 5 test invitations available. No live database used.')
