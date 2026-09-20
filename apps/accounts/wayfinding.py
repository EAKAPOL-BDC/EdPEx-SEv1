"""Read-only navigation from authorized view context, never browser history.

Links are an aid, not authorization: every destination retains its own checks.
Only context supplied by the view identifies a scope/round/version. No Referer,
next URL, database lookup by URL parameter, or state-changing link is used here.
"""
from functools import lru_cache

from django.urls import reverse

from .permissions import can_access


COLLECTION_ACTIONS = ('selfassessment.assign', 'round.manage', 'calculation.run', 'result.submit', 'result.review')
SURVEY_ACTIONS = ('round.manage', 'calculation.run', 'result.submit', 'result.review')


def page_navigation(context):
    request = context['request']
    match = request.resolver_match
    route = match.url_name if match else ''
    scope = context.get('scope')
    from django.contrib.auth.models import AnonymousUser
    user = getattr(request,'user',AnonymousUser())
    home_route = 'workspace' if user.is_authenticated else 'home'
    home = {'label': 'หน้าหลัก / Home', 'url': reverse(home_route)}
    crumbs = [home]
    onward = None

    @lru_cache(maxsize=None)
    def allowed(action):
        return scope is not None and can_access(user, action, scope)

    def node(name, label, *, actions=(), any_of=(), **kwargs):
        permitted = all(allowed(a) for a in actions) and (not any_of or any(allowed(a) for a in any_of))
        if scope is not None:
            kwargs.setdefault('scope_id', scope.pk)
        # Non-scoped views use an explicit helper below.
        return {'label': label, 'url': reverse(name, kwargs=kwargs) if permitted else None}

    def add(name, label, **kwargs):
        crumbs.append(node(name, label, **kwargs))

    def leaf(label):
        crumbs.append({'label': label, 'url': None})

    title = context.get('title')
    selected = context.get('selected') if hasattr(context.get('selected'), 'collection_round') else None
    r = context.get('round')
    version = context.get('version')

    if route in {'workspace', 'home'}:
        return {'crumbs': [], 'home': home, 'back': None, 'next': None}
    if route.startswith('manuals-'):
        crumbs.append({'label': 'คู่มือการใช้งาน / User manuals', 'url': reverse('manuals-home')})
        if context.get('manual'):
            leaf(context['manual']['title'])
    elif route.startswith('self-assessment-'):
        crumbs.append({'label': 'แบบประเมินของฉัน / My assessments', 'url': reverse('self-assessment-list')})
        if route == 'self-assessment-detail':
            leaf('ตอบแบบประเมิน F06 / Complete F06 assessment')
    elif route in {'password-change', 'password-change-done', 'login'}:
        leaf({'password-change': 'เปลี่ยนรหัสผ่าน / Change password',
              'password-change-done': 'เปลี่ยนรหัสผ่านแล้ว / Password changed',
              'login': 'เข้าสู่ระบบ / Sign in'}[route])
    elif route in {'survey-access', 'survey-answer'}:
        crumbs.append({'label': 'เข้าทำแบบสำรวจ / Access survey', 'url': reverse('survey-access')})
        if route == 'survey-answer':
            leaf('รับคำตอบแล้ว / Response received' if context.get('receipt') else 'แบบสำรวจ / Survey')
    elif scope is None:
        # Error pages must not manufacture scoped destinations from the URL.
        return {'crumbs': [], 'home': home, 'back': home, 'next': None}
    elif route.startswith('f04-'):
        add('f04-register', 'ทะเบียนผู้ถูกประเมิน F04 / F04 annual register', actions=('round.manage',))
        plan = context.get('plan')
        if plan:
            add('f04-plan', str(plan.fiscal_year), actions=('round.manage',), plan_id=plan.pk)
        if title:
            leaf(title)
    elif route == 'group-register':
        leaf('ทะเบียนกลุ่มและรหัส / Group and code register')
    elif route.startswith('portal-catalog'):
        add('portal-catalog', 'คลังแบบฟอร์ม / Form library', actions=('catalog.read',))
        if version:
            add('portal-catalog-detail', f'{version.instrument.code} · {version.version}',
                actions=('catalog.read',), version_id=version.pk)
        bundle = context.get('bundle')
        if bundle and route in {'portal-catalog-review', 'portal-catalog-translation'}:
            add('portal-catalog-review', 'ตรวจเนื้อหาและคำแปล / Content and translation review',
                actions=('catalog.read',), version_id=version.pk, bundle_id=bundle.pk)
        if title:
            leaf(title)
    elif route.startswith('assessment-preview'):
        add('assessment-preview-list', 'ดูแบบประเมิน / Preview assessments', actions=('catalog.read',))
        if route == 'assessment-preview':
            leaf(f"{context.get('group_code', '')} · {context.get('group_label', '')}".strip(' ·') or 'ตัวอย่างแบบประเมิน / Assessment preview')
    elif route in {'portal-members', 'portal-account-new', 'portal-revoke'}:
        add('portal-members', 'สมาชิกและบทบาท / Members and roles', actions=('role.manage',))
        if route != 'portal-members':
            leaf(title or 'จัดการสมาชิก / Manage member')
    elif route.startswith('backoffice-'):
        add('backoffice-home', 'จัดการระบบ / Administration', actions=('role.manage',))
        if route != 'backoffice-home':
            leaf({'backoffice-settings': 'ตั้งค่าพื้นที่ทำงาน / Workspace settings',
                  'backoffice-audit': 'ประวัติการดำเนินงาน / Activity history'}.get(route, 'จัดการระบบ / Administration'))
    elif route.startswith('round-'):
        add('round-list', 'จัดเตรียมรอบ / Round setup', actions=('round.manage',))
        if route == 'round-period-new':
            form = context.get('form')
            origin = form['return_to'].value() if form is not None and 'return_to' in form.fields else ''
            if origin == 'survey':
                crumbs.pop()
                add('survey-list', 'เก็บข้อมูลไม่ระบุตัวตน F01–F06 / Anonymous collection F01–F06', any_of=SURVEY_ACTIONS)
                add('survey-new', 'สร้างรอบแบบสำรวจ / Create survey round', actions=('round.manage',))
            elif origin == 'f06':
                add('round-new', 'สร้างรอบ F06 / Create F06 round', actions=('round.manage',))
        if r:
            add('round-detail', r.code, actions=('round.manage',), round_id=r.pk)
        if route not in {'round-list', 'round-detail'}:
            leaf(title or 'จัดการรอบ / Manage round')
        if route == 'round-detail' and r:
            snapshot = context.get('snapshot')
            if r.status == 'draft' and (not snapshot or snapshot.status == 'draft'):
                onward = node('round-population', 'กำหนดผู้มีสิทธิ์ตอบ / Define eligible respondents',
                    actions=('population.manage', 'source.manage'), round_id=r.pk)
            elif r.status in {'ready', 'open', 'closed', 'review', 'approved'}:
                selected = context.get('binding')
                if selected:
                    code = selected.instrument_version.instrument.code
                    dest = 'survey-collection' if hasattr(selected,'survey_profile') else 'activity-collection' if code == 'F05' else 'operator-collection' if code == 'F06' else 'survey-collection'
                    onward = node(dest, 'เปิดงานเก็บข้อมูล / Open collection', selected_id=selected.pk,
                        actions=('source.manage',) if dest=='activity-collection' else (),
                        any_of=SURVEY_ACTIONS if dest=='survey-collection' else COLLECTION_ACTIONS if dest=='operator-collection' else ())
    elif route in {'participation-manage', 'participation-setup', 'participation-results'} and selected:
        from .workflow import collection_links
        links = collection_links(user, selected)
        add('survey-list', 'รอบ คำเชิญ และติดตามผล / Collections, invitations and results', any_of=SURVEY_ACTIONS)
        crumbs.append({'label': selected.collection_round.code,
                       'url': links.get('invitations') if route!='participation-manage' else None})
        leaf({'participation-manage':'ศูนย์คำเชิญและควบคุมรอบ / Invitations and collection control',
              'participation-setup':'สร้างรอบทดสอบใหม่ / Create a test collection',
              'participation-results':'ติดตามผลและส่งตรวจ / Results and review'}[route])
    elif route.startswith(('activity-', 'survey-', 'operator-')):
        code = selected.instrument_version.instrument.code if selected else ('F05' if route.startswith('activity-') else 'F06' if route.startswith('operator-') else 'F01')
        family = 'survey' if route.startswith('survey-') or (selected and hasattr(selected,'survey_profile')) else 'activity' if code == 'F05' else 'operator' if code == 'F06' else 'survey'
        access = {'actions': ('source.manage',)} if family == 'activity' else {'any_of': COLLECTION_ACTIONS if family == 'operator' else SURVEY_ACTIONS}
        add(family + '-list', {'activity': 'กิจกรรมบุคลากร F05 / Staff activities F05',
            'operator': 'งานเก็บข้อมูล F06 / F06 collection', 'survey': 'เก็บข้อมูลไม่ระบุตัวตน F01–F06 / Anonymous collection F01–F06'}[family], **access)
        if selected:
            if family == 'survey':
                from .workflow import collection_links
                links = collection_links(user, selected)
                crumbs.append({'label': selected.collection_round.code, 'url': links.get('primary')})
            else:
                add(family + '-collection', selected.collection_round.code, selected_id=selected.pk, **access)
        if route == 'operator-assign' and selected:
            add('operator-roster', 'รายชื่อสำหรับมอบหมาย / Assignment roster',
                actions=('selfassessment.assign', 'population.manage'), selected_id=selected.pk)
        labels = {'operator-roster': 'รายชื่อสำหรับมอบหมาย / Assignment roster',
            'operator-assign': 'มอบหมายแบบประเมิน / Assign assessment',
            'operator-calculate': 'คำนวณผล F06 / Calculate F06 results',
            'operator-run': 'ตรวจและรับรองผล / Review and approve results',
            'survey-calculate': 'เตรียมผลแบบสำรวจ / Prepare survey results',
            'survey-invite': 'ออกคำเชิญ / Issue invitation',
            'activity-entry': 'บันทึกและตรวจรายการ / Entry and review',
            'activity-entry-new': 'เพิ่มกิจกรรม / Add activity'}
        if route in labels or route.endswith('-new'):
            leaf(title or labels.get(route, 'สร้างรอบเก็บข้อมูล / Create collection round'))
        if selected and route == 'operator-collection':
            if selected.collection_round.status == 'ready':
                onward = node('operator-roster', 'มอบหมายผู้ตอบ / Assign respondents',
                    actions=('selfassessment.assign', 'population.manage'), selected_id=selected.pk)
            elif selected.collection_round.status in {'closed', 'review', 'approved'}:
                onward = node('operator-calculate', 'เตรียมการคำนวณ / Prepare calculation',
                    actions=('calculation.run',), selected_id=selected.pk)
        elif selected and route == 'survey-collection' and selected.collection_round.status == 'closed':
            onward = node('survey-calculate', 'เตรียมผลแบบสำรวจ / Prepare survey results',
                actions=('calculation.run',), selected_id=selected.pk)
    elif route.startswith('insights-'):
        add('insights-list', 'สรุปผลที่รับรองแล้ว / Approved results', actions=('result.review', 'calculation.validate'))
        if route != 'insights-list':
            leaf({'insights-demo': 'ข้อมูลสาธิตและเปรียบเทียบ / Demo and comparisons',
                  'insights-compare': 'เปรียบเทียบผลจริง / Compare actual results',
                  'insights-detail': 'รายละเอียดผลรับรอง / Approved result details'}.get(route, 'ผลการดำเนินงาน / Results'))
    elif route.startswith('visualization-'):
        add('visualization-home', 'Data Visualization', actions=('result.review', 'calculation.validate'))
        if route != 'visualization-home':
            leaf('Endlessloop' if route == 'visualization-endlessloop' else 'FineReport')
    elif route == 'quality-home':
        leaf('คุณภาพข้อมูล / Data quality')
    else:
        return {'crumbs': [], 'home': home, 'back': home, 'next': None}

    # Last item is always current, including list/detail pages. Never link the
    # current page back to itself. Parent skips ancestors unavailable to user.
    crumbs[-1] = dict(crumbs[-1], url=None)
    back = next((c for c in reversed(crumbs[:-1]) if c['url']), home)
    return {'crumbs': crumbs, 'home': home, 'back': back,
            'next': onward if onward and onward['url'] else None}
