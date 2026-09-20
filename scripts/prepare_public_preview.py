"""Prepare one synthetic example only in the separate public UI preview database."""
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'edpex.public_demo')
import django
django.setup()
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone
from apps.rounds.models import RoundInstrument
from apps.rounds.services import transition_round
from apps.participation import public_setup, public_admission
from apps.participation.models import PublicCollection

if settings.SETTINGS_MODULE != 'edpex.public_demo' or settings.DATABASES['default']['NAME'] != 'edpex_m1_public_ui':
    raise RuntimeError('Separate public synthetic preview only')

with transaction.atomic():
    source = RoundInstrument.objects.select_related('collection_round__owner', 'survey_profile', 'instrument_version__instrument').get(pk='083e4afe-3a89-4941-8a48-03e55fab6d8e')
    if source.collection_round.data_kind != 'synthetic':
        raise RuntimeError('Synthetic source required')
    existing = PublicCollection.objects.filter(binding__collection_round__code='PUBLIC-PREVIEW-F01-PRIMARY').first()
    if existing:
        print('Existing preview:', existing.binding_id)
    else:
        actor = source.collection_round.owner
        now = timezone.now()
        data = dict(code='PUBLIC-PREVIEW-F01-PRIMARY', context_th='ประสบการณ์นิสิตสาขาวิชาการประถมศึกษา · ข้อมูลสมมุติ', context_en='Primary Education student experience · synthetic data',
            open_at=now-timedelta(minutes=1), due_at=now+timedelta(days=7), close_at=now+timedelta(days=8), count=20,
            source_title='จำนวนสมมุติเพื่อทดสอบหน้าเข้าประเมิน', source_reference='Synthetic reference: 20 units, no personal roster',
            privacy_notice='พื้นที่สาธิตสำหรับทดสอบการทำงานเท่านั้น โปรดใช้ข้อมูลสมมุติ ไม่กรอกชื่อ รหัส หรือข้อมูลที่ระบุตัวบุคคล หลักฐานนี้ใช้รับภาระงานหรือรางวัลจริงไม่ได้ / Demonstration only. Use synthetic data without names, IDs or identifying details. Proof cannot be used for real workload credits or rewards.',
            label_th='F01 ประสบการณ์นิสิตประถมศึกษา · ทดสอบ', label_en='F01 Primary Education student experience · test',
            expires_at=now+timedelta(days=38), workload=False, prize=True, group_code='C1', level='bachelor', programme='primary',
            setup_stamp=signing.dumps({'actor':str(actor.pk),'source':str(source.pk),'nonce':str(uuid.uuid4())},salt=public_setup.SALT))
        binding = public_setup.create_collection(actor, source, data)
        transition_round(actor, binding.collection_round, 'open', reason='Separate synthetic public UI demonstration')
        public_admission.set_published(actor, binding.pk, True)
        print('Created separate synthetic example:', binding.pk)
