"""Server-side authorization: no implicit staff, superuser, or raw-response bypass."""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import ALLOWED_PERMISSIONS, AccessScope, Membership, RoleAssignment


def _current_scope_chain(scope):
    scope_id = getattr(scope, "pk", scope)
    try:
        current_scope = AccessScope.objects.filter(pk=scope_id, active=True).first()
    except (ValidationError, ValueError, TypeError):
        return None, []
    if current_scope is None:
        return None, []
    organization_id = current_scope.organization_id
    scope_ids = [current_scope.pk]
    parent_id = current_scope.parent_id
    while parent_id:
        if parent_id in scope_ids:
            return None, []
        parent = AccessScope.objects.filter(pk=parent_id, organization_id=organization_id, active=True).first()
        if parent is None:
            return None, []
        scope_ids.append(parent.pk)
        parent_id = parent.parent_id
    return current_scope, scope_ids


def has_active_membership(user, scope):
    """Check current membership, without implying any action permission."""
    if not getattr(user, "is_authenticated", False) or not getattr(user, "pk", None):
        return False
    current_scope, _ = _current_scope_chain(scope)
    if current_scope is None:
        return False
    return Membership.objects.filter(
        user_id=user.pk, user__is_active=True, organization_id=current_scope.organization_id,
        is_active=True,
    ).exists()


def _can_access(user, action, scope, owner=None, *, delegate_descendants=False,
                delegation_start=None, delegation_end=None):
    """Check current persisted grants; scope ancestry is explicit and opt-in.

    `owner` is mandatory for self.read/self.write and may be a user or its pk.
    The grant interval is [active_from, active_until). No auth-user flag grants
    access by itself. Unsupported actions and malformed scopes fail closed.
    """
    if not isinstance(action, str) or action not in ALLOWED_PERMISSIONS or not getattr(user, "is_authenticated", False):
        return False
    user_id = getattr(user, "pk", None)
    if not user_id or not get_user_model().objects.filter(pk=user_id, is_active=True).exists():
        return False
    if action in {"self.read", "self.write"}:
        owner_id = getattr(owner, "pk", owner)
        if owner_id is None or str(owner_id) != str(user_id):
            return False
    current_scope, scope_ids = _current_scope_chain(scope)
    if current_scope is None:
        return False

    organization_id = current_scope.organization_id
    now = timezone.now()
    grants = RoleAssignment.objects.filter(
        membership__user_id=user_id,
        membership__is_active=True,
        membership__organization_id=organization_id,
        scope__organization_id=organization_id,
        scope__active=True,
        scope_id__in=scope_ids,
        active_from__lte=now,
        revoked_at__isnull=True,
    ).filter(Q(active_until__isnull=True) | Q(active_until__gt=now)).select_related("role")
    for grant in grants:
        if grant.scope_id != current_scope.pk and not grant.include_descendants:
            continue
        if delegate_descendants and not grant.include_descendants:
            continue
        if delegation_start is not None:
            if grant.active_from > delegation_start:
                continue
            if grant.active_until is not None and (delegation_end is None or delegation_end > grant.active_until):
                continue
        if isinstance(grant.role.permissions, list) and action in grant.role.permissions:
            return True
    return False


def can_access(user, action, scope, owner=None):
    return _can_access(user, action, scope, owner=owner)


def can_delegate(user, action, scope, *, active_from, active_until, include_descendants=False):
    """Delegation cannot broaden an action's scope or its authorizing interval."""
    return _can_access(
        user, action, scope, owner=user,
        delegate_descendants=include_descendants,
        delegation_start=active_from, delegation_end=active_until,
    )


def require_permission(user, action, scope, owner=None):
    if not can_access(user, action, scope, owner=owner):
        raise PermissionDenied("This action is not permitted for this user and scope.")
