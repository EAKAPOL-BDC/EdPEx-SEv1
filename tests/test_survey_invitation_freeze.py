from django.test import TestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from apps.rounds.models import PopulationMember,RespondentGroup
from apps.rounds.web_services import save_population,save_member
from apps.rounds.services import freeze_population,transition_round
from apps.surveys.operator import save_round
from apps.surveys.services import issue
from tests.test_surveys import setup_surveys

class InvitationFreezeTests(TestCase):
    @classmethod
    def setUpTestData(cls):cls.f=setup_surveys(only={'F03'})
    def test_issued_ready_round_cannot_revert_and_change_invitation_context(self):
        f=self.f;now=timezone.now()
        data={'code':'Ready invitation freeze','bundle':f.selected['F03'].translation_bundle,'period':f.period,'owner':f.actor,'open_at':now-timedelta(hours=1),'due_at':now+timedelta(days=1),'close_at':now+timedelta(days=2),'privacy_notice':'Synthetic notice','group_code':'ST1','counting_unit':'person','context_th':'บริบทตรึง','context_en':'Fixed context','assessor_role':'','study_options':[]}
        s=save_round(f.actor,f.scope,data);r=s.collection_round
        pop=save_population(f.actor,r,{'definition':'Synthetic roster','count':1,'captured_at':now,'source_title':'Synthetic source','source_location':'Fixture'})
        m=save_member(f.actor,r,{'eligible_unit_key':'READY-ONLY','group':RespondentGroup.objects.get(scope=f.scope,code='ST1')})
        freeze_population(f.actor,pop);r=transition_round(f.actor,r,'ready')
        # Reverting is supported before any invitation is issued.
        r=transition_round(f.actor,r,'draft',reason='Synthetic correction')
        r=transition_round(f.actor,r,'ready')
        issue(f.actor,s.pk,m.pk)
        with self.assertRaises(ValidationError):transition_round(f.actor,r,'draft',reason='Would change context')
        r.refresh_from_db();self.assertEqual(r.status,'ready')
