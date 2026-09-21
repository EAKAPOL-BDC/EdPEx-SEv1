"""Exercise the actual review/acknowledgement flow in integration tests."""
from apps.governance.models import Confirmation


def confirmed_post(client, url, data=None):
    payload = dict(data or {})
    review = client.post(url, payload)
    assert review.status_code == 200, review.status_code
    assert review.context and review.context.get('ticket'), 'Expected a review before mutation'
    ticket = review.context['ticket']
    assert Confirmation.objects.get(pk=ticket).used_at is None
    response = client.post(url, {**payload, 'operation_ticket':str(ticket), 'operation_ack':'yes'})
    return response
