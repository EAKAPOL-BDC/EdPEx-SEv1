"""Canonical, permission-aware links shared by home, lists and navigation."""
from django.conf import settings
from django.urls import reverse
from .permissions import can_access

SURVEY_ACTIONS = ('round.manage', 'calculation.run', 'result.submit', 'result.review')


def participation_enabled():
    return bool(getattr(settings, 'NEXORA_PARTICIPATION_ENABLED', False)
                and getattr(settings, 'NEXORA_UNLINKED_ACCESS_ENABLED', False))


def collection_links(user, selected, actions=None):
    # Historical self-assessments retain their own routes and controls.
    if not hasattr(selected, 'survey_profile'):
        return {}
    from apps.surveys.calculation_presentation import participation_hub
    scope = selected.collection_round.scope
    allowed = (lambda action: action in actions) if actions is not None else (lambda action: can_access(user, action, scope))
    if not any(allowed(a) for a in SURVEY_ACTIONS):
        return {}
    base = reverse('survey-collection', args=[scope.pk, selected.pk])
    links = {'primary': base, 'label': 'จัดการรอบ / Collection workspace', 'details': base}
    if getattr(settings, 'NEXORA_PUBLIC_ASSESSMENTS_ENABLED', False):
        manager = allowed('round.manage') and allowed('population.manage')
        if getattr(selected.survey_profile, 'intake_method', '') == 'public':
            public_url = reverse('public-assessment-manage', args=[scope.pk, selected.pk])
            if hasattr(selected, 'batch_item'):
                public_url = reverse('assessment-batch-manage', args=[scope.pk, selected.batch_item.batch_id])
            if manager:
                links.update(primary=public_url, details=public_url, label='จัดการการประเมินสาธารณะ / Public assessment management')
            return links
        if manager and allowed('source.manage'):
            if selected.instrument_version.instrument.code == 'F04':
                links['public_setup'] = reverse('f04-register', args=[scope.pk])
            else:
                links['public_setup'] = reverse('assessment-batch-new', args=[scope.pk]) + '?source=' + str(selected.pk)
            links['label'] = 'เตรียมรอบสาธารณะ / Prepare public collection'
            return links
    hub = participation_hub(selected)
    if not hub:
        return links
    links['results'] = hub
    manager = allowed('round.manage') and allowed('population.manage')
    if manager:
        links['invitations'] = reverse('participation-manage', args=[scope.pk, selected.pk])
        if (allowed('source.manage') and selected.instrument_version.status == 'published'
                and selected.translation_bundle.status == 'published'):
            links['setup'] = reverse('participation-setup', args=[scope.pk, selected.pk])
    if not manager or selected.collection_round.status in {'closed', 'review', 'approved', 'archived'}:
        links.update(primary=hub, label='ติดตามผลและส่งตรวจ / Results and review')
    else:
        links.update(primary=links['invitations'], label='ศูนย์คำเชิญและควบคุมรอบ / Invitations and collection control')
    return links
