"""Create a new aggregate-only synthetic demo, preserving the earlier demo/history."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['DJANGO_SETTINGS_MODULE']='edpex.participation_demo'
import django
django.setup()
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
from apps.participation.models import ReceiptPolicy
from apps.participation import admission, services
from apps.surveys.operator import save_round
from apps.rounds.services import transition_round

with transaction.atomic():
    if ReceiptPolicy.objects.filter(activity_code='f01-unlinked-demo').exists():
        print('Unlinked synthetic demo already exists; preserved.')
    else:
        original=ReceiptPolicy.objects.select_related('binding__collection_round__scope','binding__survey_profile').get(activity_code='f01-ui-demo',realm='test')
        b=original.binding;r=b.collection_round;p=b.survey_profile
        if r.data_kind!='synthetic':raise RuntimeError('Synthetic source required.')
        now=timezone.now()
        data=dict(owner=r.owner,open_at=now-timedelta(minutes=5),due_at=now+timedelta(days=1),close_at=now+timedelta(days=2),period=r.period,
                  code='Synthetic F01 unassigned invitations',bundle=b.translation_bundle,privacy_notice='Synthetic test: unassigned invitation hashes; no recipient roster. Keep identifying details out of answers.',
                  group_code='C1',counting_unit='person',context_th='รอบทดสอบคำเชิญไม่ผูกบุคคล',context_en='Unassigned invitation test collection',assessor_role='',study_options=p.study_options)
        new=save_round(r.owner,r.scope,data,data_kind='synthetic')
        admission.prepare_population(r.owner,new.pk,5,source_title='Synthetic aggregate population',source_reference='Five synthetic test slots; no named roster')
        services.configure_policy(r.owner,new.pk,activity_code='f01-unlinked-demo',label_th='F01 · ทดสอบคำเชิญไม่ผูกบุคคล',label_en='F01 · unassigned invitation test',expires_at=now+timedelta(days=30),workload=True,prize=True)
        admission.configure(r.owner,new.pk,5)
        ready=transition_round(r.owner,new.collection_round,'ready')
        transition_round(r.owner,ready,'open')
        print('New synthetic F01 collection prepared: 5 slots, zero PopulationMember records, no invitations minted yet.')
