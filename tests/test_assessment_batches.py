import copy
import os
import uuid
from pathlib import Path
from unittest.mock import patch
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from apps.participation import batches, public_admission
from apps.participation.models import AssessmentBatch, PublicCollection
from apps.rounds.models import CollectionRound, PopulationMember
from apps.surveys.models import Invitation
from tests.test_surveys import setup_surveys
from tests.test_public_assessments import setup_data


@override_settings(NEXORA_PARTICIPATION_ENABLED=True, NEXORA_PUBLIC_ASSESSMENTS_ENABLED=True,
                   SURVEY_ALLOW_TEST_HTTP=True, NEXORA_CONFIRM_IMPORTANT_ACTIONS=False)
class AssessmentBatchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.f = setup_surveys(only={'F01'}, data_kind='synthetic')
        cls.source = cls.f.selected['F01']

    def form(self, **changes):
        bundle = self.source.translation_bundle
        data = setup_data(self.f.actor, self.source, 'C1', level='bachelor', programme='primary')
        data.update(bundle=str(bundle.pk), period=str(self.source.collection_round.period_id),
            group_codes=['C1', 'C2.1'], confirm=True,
            setup_stamp=signing.dumps({'actor':str(self.f.actor.pk),'scope':str(self.f.scope.pk),'nonce':str(uuid.uuid4())},salt=batches.SALT))
        blank = batches.BatchForm(scope=self.f.scope, bundle=bundle)
        for name, group, level, programme, _ in blank.context_fields:
            if (group,level,programme)==('C1','bachelor','primary'):data[name]=120
            if (group,level,programme)==('C2.1','master','stem'):data[name]=40
        data.update(changes)
        form = batches.BatchForm(data=data, scope=self.f.scope, bundle=bundle)
        return form, data

    def create(self):
        form,_=self.form()
        self.assertTrue(form.is_valid(),form.errors)
        return batches.create_batch(self.f.actor,self.f.scope,form.cleaned_data)

    def test_multiple_groups_separate_counts_no_roster_and_idempotent(self):
        form,_=self.form()
        self.assertTrue(form.is_valid(),form.errors)
        batch=batches.create_batch(self.f.actor,self.f.scope,form.cleaned_data)
        rows=list(batch.items.select_related('binding__survey_profile','binding__collection_round__population_snapshot'))
        self.assertEqual({r.binding.survey_profile.group_code:r.binding.collection_round.population_snapshot.counts_by_group[r.binding.survey_profile.group_code] for r in rows},{'C1':120,'C2.1':40})
        rounds=[r.binding.collection_round_id for r in rows]
        self.assertFalse(PopulationMember.objects.filter(snapshot__collection_round_id__in=rounds).exists())
        self.assertFalse(Invitation.objects.filter(binding__collection_round_id__in=rounds).exists())
        self.assertEqual(batches.create_batch(self.f.actor,self.f.scope,form.cleaned_data).pk,batch.pk)
        self.assertEqual(batch.items.count(),2)
        self.assertFalse(PublicCollection.objects.filter(binding__batch_item__batch=batch,published=True).exists())
        self.assertTrue(CollectionRound.objects.filter(pk=self.source.collection_round_id).exists())

    def test_missing_count_and_wrong_group_rejected(self):
        form,data=self.form()
        for name,group,*_ in form.context_fields:
            if group=='C2.1':data.pop(name,None)
        invalid=batches.BatchForm(data=data,scope=self.f.scope,bundle=self.source.translation_bundle)
        self.assertFalse(invalid.is_valid());self.assertIn('group_codes',invalid.errors)
        invalid,_=self.form(group_codes=['ST1'])
        self.assertFalse(invalid.is_valid())
        self.assertFalse(AssessmentBatch.objects.exists())

    def test_service_rejects_tampered_entries(self):
        form,_=self.form();self.assertTrue(form.is_valid(),form.errors)
        values=copy.copy(form.cleaned_data)
        values['entries']=[dict(form.cleaned_data['entries'][0],programme='stem'),form.cleaned_data['entries'][1]]
        with self.assertRaises(ValidationError):batches.create_batch(self.f.actor,self.f.scope,values)
        self.assertFalse(AssessmentBatch.objects.exists())

    def test_creation_failure_rolls_back_all_contexts(self):
        form,_=self.form();self.assertTrue(form.is_valid(),form.errors)
        count=CollectionRound.objects.count()
        original=batches.build_public_collection
        calls=[]
        def fail_second(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:raise IntegrityError('Injected second context failure')
            return original(*args,**kwargs)
        with patch.object(batches,'build_public_collection',side_effect=fail_second):
            with self.assertRaises(IntegrityError):batches.create_batch(self.f.actor,self.f.scope,form.cleaned_data)
        self.assertEqual(CollectionRound.objects.count(),count)
        self.assertFalse(AssessmentBatch.objects.exists())

    def test_open_publish_and_public_choices_are_group_specific(self):
        batch=self.create()
        batches.control(self.f.actor,batch,'open')
        batches.control(self.f.actor,batch,'publish')
        client=Client()
        for group,level,programme in [('C1','bachelor','primary'),('C2.1','master','stem')]:
            response=client.post(reverse('public-assessment-choices'),{'group':group,'level':level,'programme':programme,'year':'1'},content_type='application/json')
            self.assertEqual(response.status_code,200,response.content[:500])
            expected=batch.items.get(binding__survey_profile__group_code=group)
            self.assertEqual([r['id'] for r in response.json()['collections']],[str(expected.binding_id)])
        batches.control(self.f.actor,batch,'close','Test complete')
        self.assertEqual(PublicCollection.objects.filter(binding__batch_item__batch=batch,published=True).count(),0)

    def test_control_failure_is_atomic_and_permission_checked(self):
        batch=self.create()
        with self.assertRaises(PermissionDenied):batches.control(self.f.other,batch,'open')
        original=public_admission.set_published
        calls=[]
        def fail_second(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:raise ValidationError('Injected second publish failure')
            return original(*args,**kwargs)
        with patch.object(public_admission,'set_published',side_effect=fail_second):
            with self.assertRaises(ValidationError):batches.control(self.f.actor,batch,'publish')
        self.assertFalse(PublicCollection.objects.filter(binding__batch_item__batch=batch,published=True).exists())

    def test_http_navigation_form_management_and_preserved_source(self):
        client=Client();client.force_login(self.f.actor)
        url=reverse('survey-new',args=[self.f.scope.pk])
        response=client.get(url)
        self.assertEqual(response.status_code,200)
        response=client.get(url,{'bundle':str(self.source.translation_bundle_id)})
        self.assertContains(response,'name="group_codes"')
        self.assertContains(response,'count_')
        if os.environ.get('NEXORA_BATCH_RENDER'):
            path=Path(os.environ['NEXORA_BATCH_RENDER']);path.mkdir(parents=True,exist_ok=True)
            for locale in ['th','en']:
                client.post(reverse('portal-language'), {'language': locale})
                localized=client.get(url,{'bundle':str(self.source.translation_bundle_id)})
                self.assertEqual(localized.status_code, 200)
                # Actual server template rendering for visual QA, with existing static assets.
                html=localized.content.decode().replace('"/static/','"http://127.0.0.1:8768/static/')
                (path/f'form-{locale}.html').write_text(html,encoding='utf-8')
        source_response=client.get(reverse('survey-collection',args=[self.f.scope.pk,self.source.pk]))
        self.assertContains(source_response,reverse('assessment-batch-new',args=[self.f.scope.pk])+'?source='+str(self.source.pk))
        self.assertNotContains(source_response,'Invitation codes')
        form,data=self.form()
        data={k:(v.strftime('%Y-%m-%dT%H:%M') if hasattr(v,'strftime') else v) for k,v in data.items()}
        response=client.post(reverse('assessment-batch-new',args=[self.f.scope.pk]),data)
        self.assertEqual(response.status_code,302,response.content[:1000])
        self.assertEqual(client.get(response.url).status_code,200)
        self.assertEqual(client.get(reverse('survey-list',args=[self.f.scope.pk])).status_code,200)

    @override_settings(NEXORA_CONFIRM_IMPORTANT_ACTIONS=True)
    def test_confirmation_preserves_multi_value_groups_and_counts(self):
        import re
        client=Client();client.force_login(self.f.actor)
        form,data=self.form()
        data={k:(v.strftime('%Y-%m-%dT%H:%M') if hasattr(v,'strftime') else v) for k,v in data.items()}
        url=reverse('assessment-batch-new',args=[self.f.scope.pk])
        review=client.post(url,data)
        self.assertEqual(review.status_code,200)
        ticket=re.search(r'name="operation_ticket" value="([^"]+)"',review.content.decode()).group(1)
        self.assertFalse(AssessmentBatch.objects.exists())
        result=client.post(url,dict(data,operation_ticket=ticket,operation_ack='yes'))
        self.assertEqual(result.status_code,302,result.content[:1000])
        self.assertEqual(AssessmentBatch.objects.get().items.count(),2)


    def test_combined_launch_rollback_status_and_list_filters(self):
        from apps.participation.collection_presentation import collection_state
        from tests.ui_render_export import export
        batch=self.create()
        original=public_admission.set_published
        calls=[]
        def fail_second(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:raise ValidationError('Injected publication failure')
            return original(*args,**kwargs)
        with patch.object(public_admission,'set_published',side_effect=fail_second):
            with self.assertRaises(ValidationError):batches.control(self.f.actor,batch,'launch')
        self.assertEqual(set(batch.items.values_list('binding__collection_round__status',flat=True)),{'ready'})
        self.assertFalse(PublicCollection.objects.filter(binding__batch_item__batch=batch,published=True).exists())
        batches.control(self.f.actor,batch,'launch')
        self.assertEqual(set(batch.items.values_list('binding__collection_round__status',flat=True)),{'open'})
        client=Client();client.force_login(self.f.actor)
        url=reverse('survey-list',args=[self.f.scope.pk])
        opened=client.get(url,{'status':'open'})
        self.assertEqual(opened.context['total'],1)
        export(opened,'list-open')
        export(client.get(reverse('assessment-batch-manage',args=[self.f.scope.pk,batch.pk])),'batch-open')
        export(client.get(reverse('assessment-batch-new',args=[self.f.scope.pk])),'choose')
        batches.control(self.f.actor,batch,'close','Completed test')
        closed=client.get(url,{'status':'closed'})
        self.assertEqual(closed.context['total'],1)
        export(closed,'list-closed')
        managed=client.get(reverse('assessment-batch-manage',args=[self.f.scope.pk,batch.pk]))
        self.assertEqual(managed.context['state']['key'],'closed')
        export(managed,'batch-closed')
        self.assertEqual(client.get(url,{'status':'open'}).context['total'],0)
        for row in batch.items.select_related('binding__collection_round'):
            self.assertEqual(collection_state(row.binding)['key'],'closed')
