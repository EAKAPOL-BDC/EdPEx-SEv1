from django.utils.html import format_html
"""Presentation helpers; existing persisted permissions remain authoritative."""
from django import template
from apps.accounts.permissions import can_access

register = template.Library()


@register.filter
def instrument_title(value):
    from apps.catalog.presentation import instrument_title as current_title
    return current_title(value)


@register.simple_tag(takes_context=True)
def group_badge(context, code, fallback='', language=None, code_only=False):
    from apps.catalog.group_registry import group_info
    from django.utils.html import format_html
    row = group_info(code, language or context.get('locale') or context.get('LANGUAGE_CODE', 'th'), fallback)
    badge = format_html('<span class="nx-group-code" data-group-code="{}">{}</span>', row['code'], row['code'])
    if code_only:
        return badge
    return format_html('<span class="nx-group-label">{} <span>· {}</span></span>', badge, row['label'])


@register.simple_tag(takes_context=True)
def group_text(context, code, fallback='', language=None):
    from apps.catalog.group_registry import group_display
    return group_display(code, fallback, language or context.get('locale') or context.get('LANGUAGE_CODE', 'th'))


@register.simple_tag(takes_context=True)
def group_reference(context, code, language=None):
    from apps.catalog.group_registry import group_info
    return group_info(code, language or context.get('LANGUAGE_CODE', 'th'))


@register.filter
def management_field_class(field):
    """Layout only; preserve Django widgets, names, disabled state and validation."""
    from django.forms import CheckboxInput, CheckboxSelectMultiple, SelectMultiple, Textarea
    widget = field.field.widget
    if isinstance(widget, CheckboxInput):
        return 'is-check is-wide'
    if isinstance(widget, (Textarea, CheckboxSelectMultiple, SelectMultiple)):
        return 'is-wide'
    if field.name in ('title_th', 'source_location', 'reason', 'definition', 'group_code', 'group'):
        return 'is-wide'
    return ''


@register.filter
def answer_type_label(value, language):
    from apps.catalog.management_forms import QuestionForm
    label = dict(QuestionForm.base_fields['answer_type'].choices).get(value, value)
    return ui_wording(label, language)


@register.simple_tag(takes_context=True)
def portal_navigation(context):
    request = context['request']
    scope = context.get('scope')
    scopes = context.get('scopes', [])
    if scope is None and len(scopes) == 1:
        scope = scopes[0]['scope']
    result = {'scope': scope, 'active': request.resolver_match.url_name if request.resolver_match else ''}
    selected = context.get('selected')
    if result['active'] == 'operator-run' and selected is not None:
        code = selected.instrument_version.instrument.code
        if hasattr(selected,'survey_profile'):
            result['active']='survey-collection'
        elif code != 'F06':
            result['active'] = 'activity-collection' if code == 'F05' else 'survey-collection'
    known_actions = next((item['actions'] for item in scopes if item['scope']==scope), None)
    menu_allowed = lambda action: action in known_actions if known_actions is not None else can_access(request.user, action, scope)
    if scope is not None and request.user.is_authenticated:
        result['insights'] = all(menu_allowed(action) for action in ('result.review','calculation.validate'))
        result['activities'] = menu_allowed('source.manage')
        result['catalog'] = menu_allowed('catalog.read')
        result['round_setup'] = menu_allowed('round.manage')
        result['members'] = menu_allowed('role.manage')
        result['surveys'] = any(menu_allowed(action) for action in ('round.manage','calculation.run','result.submit','result.review'))
        result['collection'] = any(menu_allowed(action) for action in
            ('selfassessment.assign', 'round.manage', 'calculation.run', 'result.submit', 'result.review'))
    if scope is not None and selected is not None and hasattr(selected, 'collection_round') and request.user.is_authenticated:
        from apps.accounts.workflow import collection_links
        result['workflow'] = collection_links(request.user, selected, known_actions)
    result['collect_active'] = result['active'].startswith(('survey-', 'round-')) and not result.get('workflow', {}).get('results')
    result['results_active'] = result['active'] in {'participation-results','survey-calculate','operator-run'} or (request.resolver_match and request.resolver_match.url_name=='operator-run')
    if scope is not None and request.user.is_authenticated and (result.get('surveys') or result.get('insights')):
        from apps.governance.models import WorkspaceRefresh
        result['refreshed']=WorkspaceRefresh.objects.filter(scope=scope,status='completed').exists()
    return result


@register.filter
def starts_with(value, prefix):
    return str(value).startswith(prefix)


@register.filter
def ui_wording(value, language):
    """Select a short UI label; respondent translations stay in reviewed bundles."""
    parts = str(value).split(' / ', 1)
    return parts[1] if language == 'en' and len(parts) == 2 else parts[0]


@register.simple_tag(takes_context=True)
def bilingual(context, label):
    return ui_wording(label, context.get('LANGUAGE_CODE', 'th'))


@register.simple_tag(takes_context=True)
def cancel_destination(context):
    """Fixed internal destinations; cancel never submits or trusts Referer/next."""
    nav = context.get('page_nav') or page_navigation(context)
    return (nav['back'] or nav['home'])['url']


@register.simple_tag(takes_context=True)
def page_navigation(context):
    from apps.accounts.wayfinding import page_navigation as build_navigation
    return build_navigation(context)


@register.filter
def plain_method(value):
    return {'anonymous_self_report':'ผู้ตอบรายงานเองแบบไม่ระบุตัวตน','self_report':'ผู้ตอบประเมินตนเอง','survey':'แบบสำรวจ','verified_activity':'ทะเบียนกิจกรรมที่ตรวจหลักฐาน'}.get(value,value)

@register.filter
def quality_label(value):
    return {'valid_n':'ผู้ตอบที่ให้ข้อมูลพอคำนวณ','eligible':'ผู้มีสิทธิ์ทั้งหมด','submitted':'ผู้ส่งคำตอบ','missing':'คำตอบที่ไม่มีข้อมูล','not_responded':'ผู้ยังไม่ส่งคำตอบ','not_submitted':'ผู้ยังไม่ส่งคำตอบ','passed':'ผู้ผ่านเกณฑ์','below_threshold':'ผู้มีข้อมูลแต่ยังไม่ผ่านเกณฑ์','na':'ไม่เกี่ยวข้อง','skipped':'เลือกข้าม','not_shown':'ข้อที่ไม่แสดง','unable_to_assess':'ยังประเมินไม่ได้','valid_answers':'คำตอบที่นำมาคำนวณ','complete':'คำตอบครบ','submitted_partial':'คำตอบบางส่วน'}.get(value,value)


@register.filter
def indicator_title(value):
    from apps.catalog.indicator_alignment import indicator_title as title
    return title(value.code, value.display_name_th)

@register.simple_tag
def collection_kind(round):
    if getattr(round,'data_kind','real')=='synthetic':
        return format_html('<span class="result-badge">{}</span>','ข้อมูลสมมุติ · SYNTHETIC')
    return format_html('<span class="result-badge">{}</span>','รอเก็บจริง · Pending real collection' if not getattr(round,'schedule_confirmed',True) else 'ข้อมูลจริง · REAL')


@register.simple_tag
def field_guidance(field):
    from apps.accounts.field_guidance import guidance
    result = guidance(field)
    if result['help']:
        field.field.widget.attrs['aria-describedby'] = field.auto_id + '_guide'
    return result
