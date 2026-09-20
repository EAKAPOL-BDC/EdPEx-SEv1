import hashlib
import json
import struct
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.contrib.staticfiles import finders

from apps.accounts.models import Organization, AccessScope, Membership, Role, RoleAssignment
from apps.manuals.views import catalog, source_digest


class ManualArtifactsTests(SimpleTestCase):
    def test_every_guide_has_readable_allowlisted_illustrations_matching_files(self):
        data,_=catalog()
        used=set()
        for manual in data['manuals']:
            figures=[f for s in manual['sections'] for f in s.get('figures',[])]
            with self.subTest(slug=manual['slug']):
                self.assertGreaterEqual(len(figures),3)
                self.assertEqual(manual['figure_count'],len(figures))
                self.assertEqual([f['number'] for f in figures],list(range(1,len(figures)+1)))
                for figure in figures:
                    self.assertRegex(figure['filename'],r'^[a-z0-9-]+\.png$')
                    path=finders.find('manuals/illustrations/'+figure['filename'])
                    self.assertIsNotNone(path)
                    payload=Path(path).read_bytes()
                    self.assertEqual(payload[:8],b'\x89PNG\r\n\x1a\n')
                    self.assertEqual(struct.unpack('>II',payload[16:24]),(2160,1200))
                    self.assertEqual(hashlib.sha256(payload).hexdigest(),figure['sha256'])
                    self.assertTrue(figure['alt'])
                    self.assertEqual(len(figure['keys']),3)
                    used.add(figure['key'])
        self.assertEqual(len(used),16)

    def test_all_groups_forms_and_role_guides_have_matching_pdfs(self):
        data, manifest=catalog()
        groups=json.loads((settings.BASE_DIR/'catalog/groups.json').read_text())
        forms=json.loads((settings.BASE_DIR/'catalog/instruments.json').read_text())
        respondents=[m for m in data['manuals'] if m['category']=='respondents']
        self.assertEqual({m['group'] for m in respondents},{g['code'] for g in groups})
        self.assertEqual(len(respondents),17)
        self.assertEqual(len(data['manuals']),26)
        self.assertEqual(len(manifest['manuals']),26)
        for m in data['manuals']:
            with self.subTest(slug=m['slug']):
                if m['group']:
                    self.assertEqual(m['forms'],[f['instrument_id'] for f in forms if m['group'] in f['group_codes']])
                record=manifest['manuals'][m['slug']]
                payload=(settings.BASE_DIR/'docs/manuals/pdf'/m['filename']).read_bytes()
                self.assertTrue(payload.startswith(b'%PDF-'))
                self.assertEqual(hashlib.sha256(payload).hexdigest(),record['sha256'])
                self.assertEqual(source_digest(m),record['source_sha256'])
                self.assertGreaterEqual(record['pages'],4)
                self.assertEqual(len({s['id'] for s in m['sections']}),len(m['sections']))

    def test_critical_differences_are_documented(self):
        data,_=catalog(); by_slug={m['slug']:m for m in data['manuals']}
        staff=json.dumps(by_slug['respondent-st1'],ensure_ascii=False)
        self.assertIn('F06 แก้และส่ง revision ใหม่ได้',staff)
        self.assertIn('หลังส่ง F01-F04 ไม่สามารถแก้คำตอบ',staff)
        self.assertIn('ไม่บังคับแนบหลักฐาน',staff)
        self.assertIn('30-90',staff)
        for slug in ['respondent-c2-2','respondent-co-3']:
            self.assertTrue(any(s['id']=='english' for s in by_slug[slug]['sections']))
        dev=json.dumps(by_slug['developer'],ensure_ascii=False)
        self.assertIn('edpex_admin_self_review',dev)
        self.assertIn('restore_tested:false',dev)


class ManualWebTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org=Organization.objects.create(name='Manual test organization')
        cls.scope=AccessScope.objects.create(organization=cls.org,code='A',name='Authorized workspace')
        cls.other=AccessScope.objects.create(organization=cls.org,code='B',name='DO-NOT-SHOW-OTHER-SCOPE')
        cls.user=get_user_model().objects.create_user(username='manual-reader')
        cls.member=Membership.objects.create(user=cls.user,organization=cls.org)
        role=Role.objects.create(code='manual-auditor',permissions=['audit.read'])
        RoleAssignment.objects.create(membership=cls.member,role=role,scope=cls.scope)

    def test_public_hub_group_search_and_escaped_input(self):
        response=self.client.get(reverse('manuals-home'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.context['manuals']),26)
        response=self.client.get(reverse('manuals-home'),{'q':'C2.2','category':'respondents'})
        self.assertTrue(any(m['group']=='C2.2' for m in response.context['manuals']))
        response=self.client.get(reverse('manuals-home'),{'q':'<script>alert(1)</script>'})
        self.assertNotContains(response,'<script>alert(1)</script>')
        self.assertEqual(response.context['manuals'],[])

    def test_public_can_read_and_download_all_17_respondent_guides(self):
        data,_=catalog()
        for m in data['manuals']:
            if m['access']!='public':continue
            with self.subTest(slug=m['slug']):
                response=self.client.get(reverse('manuals-detail',args=[m['slug']]))
                self.assertEqual(response.status_code,200)
                self.assertContains(response,m['title'])
                self.assertContains(response,'ภาพจำลองอธิบายขั้นตอน')
                for section in m['sections']:
                    for figure in section.get('figures',[]):
                        self.assertContains(response,'src="/static/manuals/illustrations/'+figure['filename']+'"')
                        self.assertContains(response,'id="figure-'+str(figure['number'])+'"')
                for s in m['sections']:
                    self.assertContains(response,'id="'+s['id']+'"')
                response=self.client.get(reverse('manuals-download',args=[m['slug']]))
                payload=b''.join(response.streaming_content)
                self.assertTrue(payload.startswith(b'%PDF-'))
                self.assertEqual(response['Content-Type'],'application/pdf')
                self.assertIn('attachment;',response['Content-Disposition'])

    def test_internal_guides_require_sign_in_for_html_and_pdf(self):
        data,_=catalog()
        for m in data['manuals']:
            if m['access']=='public':continue
            for route in ['manuals-detail','manuals-download']:
                response=self.client.get(reverse(route,args=[m['slug']]))
                self.assertEqual(response.status_code,302)
                self.assertTrue(response['Location'].startswith('/login/?next='))

    def test_signed_in_reader_can_open_every_internal_guide_without_grant_changes(self):
        self.client.force_login(self.user)
        data,_=catalog()
        with CaptureQueriesContext(connection) as queries:
            for m in data['manuals']:
                if m['access']=='public':continue
                response=self.client.get(reverse('manuals-detail',args=[m['slug']]))
                self.assertEqual(response.status_code,200)
                response=self.client.get(reverse('manuals-download',args=[m['slug']]))
                self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF-'))
        writes=[q['sql'] for q in queries if q['sql'].lstrip().upper().startswith(('INSERT','UPDATE','DELETE'))]
        self.assertEqual(writes,[])
        self.assertEqual(RoleAssignment.objects.count(),1)

    def test_related_work_links_enforce_scope_and_revocation(self):
        self.client.force_login(self.user)
        response=self.client.get(reverse('manuals-detail',args=['audit-reader']))
        self.assertContains(response,reverse('backoffice-audit',args=[self.scope.pk]))
        self.assertNotContains(response,'DO-NOT-SHOW-OTHER-SCOPE')
        self.assertEqual(self.client.get(reverse('backoffice-audit',args=[self.other.pk])).status_code,403)
        Membership.objects.filter(pk=self.member.pk).update(is_active=False)
        response=self.client.get(reverse('manuals-detail',args=['audit-reader']))
        self.assertEqual(response.context['work_links'],[])

    def test_unknown_paths_methods_and_missing_or_stale_pdfs(self):
        self.assertEqual(self.client.get('/manuals/unknown/download/').status_code,404)
        self.assertEqual(self.client.get('/manuals/..%2F..%2Fedpex/settings.py/download/').status_code,404)
        self.assertEqual(self.client.post(reverse('manuals-home'),{}).status_code,405)
        self.assertEqual(self.client.post(reverse('manuals-download',args=['respondent-c1']),{}).status_code,405)
        with patch.object(Path,'read_bytes',side_effect=FileNotFoundError):
            self.assertEqual(self.client.get(reverse('manuals-download',args=['respondent-c1'])).status_code,503)
        with patch('apps.manuals.views.source_digest',return_value='stale'):
            self.assertEqual(self.client.get(reverse('manuals-download',args=['respondent-c1'])).status_code,503)
        with patch.object(Path,'read_bytes',return_value=b'%PDF-1.7 tampered'):
            self.assertEqual(self.client.get(reverse('manuals-download',args=['respondent-c1'])).status_code,503)

    def test_menu_present_without_displacing_sidebar_and_survey_opens_new_tab(self):
        self.assertContains(self.client.get(reverse('home')),reverse('manuals-home'))
        self.client.force_login(self.user)
        response=self.client.get(reverse('workspace'))
        html=response.content.decode()
        start=html.index('<aside class="workspace-sidebar"')
        end=html.index('</aside>',start)
        self.assertIn('href="/manuals/"',html[start:end])
        survey=self.client.get(reverse('survey-access'),secure=True)
        self.assertContains(survey,'target="_blank" rel="noopener noreferrer"')

    def test_head_download_and_private_cache_headers(self):
        self.client.force_login(self.user)
        response=self.client.head(reverse('manuals-download',args=['developer']))
        self.assertEqual(response.status_code,200)
        self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(response['X-Content-Type-Options'],'nosniff')
