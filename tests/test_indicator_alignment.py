"""Reference traceability, review boundaries and unchanged scoring contracts."""
import csv
import io
import json
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, SimpleTestCase, Client
from django.urls import reverse
from apps.accounts.models import Organization, AccessScope
from apps.catalog.seeding import seed_catalog
from apps.catalog.models import InstrumentVersion, InstrumentContent, Indicator, source_hash
from apps.catalog.services import source_texts
from apps.catalog.management_services import editor_token, bundle_readiness
from apps.catalog.indicator_alignment import reference, by_code, indicator_title, measurement_note
from apps.catalog.indicator_wording import prepare, INSTRUCTIONS
from apps.catalog.alignment_web import crosswalk
from apps.catalog.preview import build_preview
from apps.calculations.dashboard import presentation_rows
from tests.m2_fixtures import grant


class SourceAlignmentTests(SimpleTestCase):
    def test_all_63_codes_trace_to_original_pages_and_preserve_units(self):
        baseline=json.loads((settings.BASE_DIR/'catalog/indicators.json').read_text(encoding='utf-8'))
        self.assertEqual(len(by_code()),63)
        self.assertEqual(set(by_code()),{r['code'] for r in baseline})
        for r in baseline:
            item=by_code()[r['code']]
            self.assertEqual((item['unit'],item['direction']),(r['unit'],r['direction']))
            self.assertTrue(item['original_title'])
            self.assertTrue(all(1<=p<=13 for p in item['pages']))
        self.assertEqual(len(reference()['source']['sha256']),64)
        self.assertIn('ไม่พึงพอใจ',indicator_title('7.2-8'))
        self.assertNotEqual(indicator_title('7.2-13'),indicator_title('7.2-17'))
        self.assertIn('ค่าต่ำ',measurement_note('7.2-8'))
        self.assertIn('ผู้มีสิทธิ์ทั้งหมด',measurement_note('7.3-43'))
        self.assertIn('0 ชั่วโมง',measurement_note('7.3-44',method='anonymous_self_report',formula_version='2.1-quantitative'))


class AlignmentWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor=get_user_model().objects.create_user(username='alignment-editor')
        cls.reader=get_user_model().objects.create_user(username='alignment-reader')
        org=Organization.objects.create(name='Synthetic indicator audit')
        cls.scope=AccessScope.objects.create(organization=org,code='ALIGN',name='Alignment test')
        cls.foreign=AccessScope.objects.create(organization=org,code='OTHER',name='Foreign test')
        grant(cls.actor,cls.scope,['catalog.read','catalog.edit','catalog.publish','translation.review'],'alignment-editor')
        grant(cls.reader,cls.scope,['catalog.read'],'alignment-reader')
        cls.versions=seed_catalog(cls.scope,cls.actor)['instrument_versions']

    def setUp(self):
        self.client=Client();self.client.force_login(self.actor)

    def draft(self,code,number='1.2-readable'):
        source=self.versions[code]
        return prepare(self.actor,source,number,editor_token(self.actor,source))

    def test_crosswalk_renders_actual_selected_bindings_and_exports_without_writes(self):
        before=InstrumentVersion.objects.count()
        url=reverse('indicator-alignment',args=[self.scope.pk])
        page=self.client.get(url)
        self.assertEqual(page.status_code,200)
        self.assertEqual(len(page.context['rows']),63)
        self.assertEqual(page.context['issue_count'],0)
        self.assertContains(page,'C3.2')
        self.assertEqual(self.versions['F01'].bindings.get(indicator__code='7.4-8').group_rules['group_codes'],['C1','C2.1','C2.2','C3.1'])
        csv_response=self.client.get(reverse('indicator-alignment-export',args=[self.scope.pk]))
        rows=list(csv.DictReader(io.StringIO(csv_response.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows),63)
        self.assertEqual(next(r for r in rows if r['indicator']=='7.3-54')['form'],'F06')
        self.assertNotIn('answers',rows[0])
        self.assertEqual(InstrumentVersion.objects.count(),before)
        self.assertEqual(self.client.get(reverse('indicator-alignment',args=[self.foreign.pk])).status_code,403)

    def test_draft_keeps_originals_scores_bindings_custom_wording_and_review_gate(self):
        source=self.versions['F03']
        custom=source.questions.get(question_id='F03-S01');custom.text_th='ข้อความเฉพาะของหน่วยงาน';custom.save()
        before=source_texts(source)
        target=self.draft('F03')
        self.assertEqual(source_texts(source),before)
        self.assertEqual(target.based_on_id,source.pk)
        self.assertEqual(target.status,'draft');self.assertFalse(target.instructions_curated)
        self.assertEqual(target.questions.get(question_id=custom.question_id).text_th,custom.text_th)
        self.assertIn(custom.question_id,target.source_metadata['wording_custom_preserved'])
        self.assertIn('ไม่พึงพอใจ',target.questions.get(question_id='F03-D01').text_th)
        for old in source.questions.all():
            new=target.questions.get(question_id=old.question_id)
            for field in ('required_rule','visibility_rule','scale','group_codes','answer_type','active'):
                self.assertEqual(getattr(new,field),getattr(old,field))
            self.assertEqual(list(new.options.order_by('position').values_list('code','score','answer_status')),
                             list(old.options.order_by('position').values_list('code','score','answer_status')))
        for old in source.bindings.all():
            new=target.bindings.get(indicator=old.indicator)
            self.assertEqual((new.formula_id,new.group_rules,new.dimensions,new.indicator_snapshot),
                             (old.formula_id,old.group_rules,old.dimensions,old.indicator_snapshot))
        bundle=target.translation_bundles.latest('created_at')
        self.assertFalse(bundle_readiness(target,bundle)['ready'])
        self.assertFalse(bundle.translations.filter(status='approved').exists())
        for qid in target.source_metadata['wording_changed']:
            key=qid+'.text';entry=bundle.translations.get(content_key=key,locale='en')
            self.assertEqual(entry.source_hash,source_hash(source_texts(target)[key]));self.assertTrue(entry.text)

    def test_all_supported_forms_prepare_and_f06_uses_missions_and_strategies(self):
        for code in ('F01','F02','F04','F06'):
            draft=self.draft(code)
            self.assertEqual(draft.contents.get(content_key=code+'.instruction').text_th,INSTRUCTIONS[code][0])
            self.assertEqual([r['issues'] for r in crosswalk(self.scope,[draft]) if r['form']==code],
                             [[] for r in by_code().values() if r['form']==code])
        form,parts,instructions,fallback=build_preview(draft,'ST1','th',None)
        titles={p['key']:p['title'] for p in parts}
        self.assertIn('พันธกิจ',titles['M']);self.assertIn('กลยุทธ์',titles['T'])
        self.assertNotIn('F06-P01',form.fields)
        self.assertIn('ไม่ต้องแนบหลักฐาน',' '.join(instructions))

    def test_custom_instructions_preserved_and_stock_f06_instructions_replaced(self):
        source=self.versions['F06']
        stock=json.loads((settings.BASE_DIR/'apps/catalog/data/indicator_instruction_history.json').read_text(encoding='utf-8'))['F06']
        content=InstrumentContent.objects.create(version=source,content_key='F06.instruction',kind='instruction',audience='respondent',text_th=stock)
        first=self.draft('F06')
        self.assertNotIn('บันทึกฉบับร่าง',first.contents.get(content_key='F06.instruction').text_th)
        content.text_th='ประกาศการใช้ข้อมูลเฉพาะหน่วยงาน';content.save()
        second=self.draft('F06','custom-readable')
        self.assertEqual(second.contents.get(content_key='F06.instruction').text_th,content.text_th)
        self.assertTrue(second.source_metadata['wording_custom_instructions_preserved'])
        self.assertTrue(second.contents.filter(content_key='F06.indicator-instruction').exists())

    def test_stale_snapshot_permissions_and_duplicate_version_do_not_mutate_source(self):
        source=self.versions['F01'];token=editor_token(self.actor,source)
        q=source.questions.get(question_id='F01-D01');q.text_th='แก้ไขหลังเปิดหน้าจอ';q.save()
        count=InstrumentVersion.objects.count()
        with self.assertRaises(ValidationError):prepare(self.actor,source,'stale',token)
        self.assertEqual(InstrumentVersion.objects.count(),count)
        url=reverse('indicator-wording-prepare',args=[self.scope.pk,source.pk])
        page=self.client.get(url);self.assertEqual(page.status_code,200)
        token=page.context['form']['snapshot'].value()
        def confirmed_post(payload):
            before=InstrumentVersion.objects.count()
            preview=self.client.post(url,payload)
            self.assertEqual(preview.status_code,200)
            self.assertTemplateUsed(preview,'governance/confirm.html')
            self.assertEqual(InstrumentVersion.objects.count(),before)
            return self.client.post(url,{**payload,'operation_ticket':str(preview.context['ticket']),'operation_ack':'yes'})
        self.assertEqual(confirmed_post({'snapshot':token,'new_version':'readable-web','confirm':'on'}).status_code,302)
        self.assertEqual(InstrumentVersion.objects.count(),count+1)
        self.assertEqual(confirmed_post({'snapshot':token,'new_version':'readable-web','confirm':'on'}).status_code,422)
        self.assertEqual(InstrumentVersion.objects.count(),count+1)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(confirmed_post({'snapshot':token,'new_version':'unauthorized','confirm':'on'}).status_code,403)
        self.assertEqual(InstrumentVersion.objects.count(),count+1)

    def test_report_labels_do_not_change_indicator_records_or_reveal_suppressed_values(self):
        original=dict(Indicator.objects.filter(scope=self.scope).values_list('code','display_name_th'))
        row={'indicator':'7.2-8','group':'C1','dimension':'','unit':'percent','status':'suppressed','method':'survey','formula':{'instrument_version':'1.1'}}
        card=presentation_rows([row],self.scope,self.versions['F01'].pk)[0]
        self.assertIn('ไม่พึงพอใจ',card['label']);self.assertFalse(card['has_value'])
        self.assertNotIn('value',card);self.assertNotIn('numerator',card)
        self.assertEqual(original,dict(Indicator.objects.filter(scope=self.scope).values_list('code','display_name_th')))


class AnonymousWordingCalculationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from tests import test_governance as fixtures
        fixtures.GovernanceTests.setUpTestData.__func__(cls)

    def test_published_clone_collects_anonymously_and_replays_with_actual_version(self):
        from tests import test_governance as fixtures
        from apps.surveys import services
        from apps.surveys.schema import respondent_schema
        from apps.surveys.calculations import calculate
        from apps.calculations.models import CalculationRun
        from apps.calculations.services import validate_run
        from apps.rounds.services import transition_round
        from django.utils import timezone
        from decimal import Decimal
        original=self.bundles['F06'].instrument_version
        original.refresh_from_db()
        checksum=original.checksum
        target=prepare(self.actor,original,'1.2-readable',editor_token(self.actor,original))
        from apps.catalog.management_services import prepare_translations
        from apps.catalog.services import approve_translation, translation_review_snapshot, publish_bundle, publish_instrument_version
        target.instructions_curated=True;target.save()
        bundle=prepare_translations(self.actor,target.pk)
        for entry in bundle.translations.all():
            approve_translation(self.actor,entry,reviewed_token=translation_review_snapshot(self.actor,entry)['reviewed_token'])
        publish_bundle(self.actor,bundle);publish_instrument_version(self.actor,target)
        bundle.refresh_from_db();self.bundles={'F06':bundle}
        selected=fixtures.GovernanceTests.round(self,'F06')
        schema=respondent_schema(selected.survey_profile,{},'th')
        payload={q['id']:{'status':'answered','value':4} for q in schema['questions'] if q['type']=='integer_scale'}
        for member in selected.collection_round.population_snapshot.members.all():
            secret=services.exchange(services.issue(self.actor,selected.pk,member.pk))
            services.save(secret,payload,0,submit=True)
        transition_round(self.actor,selected.collection_round,'closed',reason='Synthetic completed wording trial')
        receipt=calculate(self.actor,selected.pk,timezone.now(),'readable-f06')
        run=CalculationRun.objects.get(pk=receipt['run_id'])
        self.assertEqual(validate_run(self.actor,run_id=run.pk)['status'],'verified')
        self.assertTrue(all(s.definition['instrument']['version']=='1.2-readable' for s in run.inputs.all()))
        self.assertEqual(Decimal(run.results.get(indicator_code='7.4-3').payload['value']),Decimal(100))
        self.assertNotIn('PRIVATE-',json.dumps(list(run.inputs.values('payload')),default=str))
        original.refresh_from_db();self.assertEqual(original.checksum,checksum);self.assertEqual(original.status,'published')
