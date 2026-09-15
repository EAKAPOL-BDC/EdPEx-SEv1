"""Narrow account operations for future views/jobs, using persisted permissions."""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.auditlog.services import record_event

from .models import AccessScope, Role, RoleAssignment, UserPreference
from .permissions import can_delegate, require_permission


def read_profile(*, actor, scope, owner):
    scope = AccessScope.objects.get(pk=scope.pk)
    require_permission(actor, "self.read", scope, owner=owner)
    owner = get_user_model().objects.get(pk=owner.pk)
    preference = UserPreference.objects.filter(user=owner).first()
    return {
        "user_id": owner.pk,
        "username": owner.get_username(),
        "preferred_locale": preference.preferred_locale if preference else "th",
    }


@transaction.atomic
def update_profile_locale(*, actor, scope, owner, preferred_locale):
    scope = AccessScope.objects.get(pk=scope.pk)
    require_permission(actor, "self.write", scope, owner=owner)
    if preferred_locale not in {"th", "en"}:
        raise ValidationError({"preferred_locale": "Supported locales are th and en."})
    preference, _ = UserPreference.objects.get_or_create(user=owner)
    preference.preferred_locale = preferred_locale
    preference.save()
    record_event(scope.organization, actor, "profile.locale_changed", "UserPreference", preference.pk,
                 metadata={"scope_id": str(scope.pk), "locale": preferred_locale})
    return preference


@transaction.atomic
def assign_role(*, actor, scope, membership, role, active_from=None, active_until=None, include_descendants=False):
    scope = AccessScope.objects.get(pk=scope.pk)
    require_permission(actor, "role.manage", scope)
    role = Role.objects.select_for_update().get(pk=role.pk)
    assignment = RoleAssignment(
        membership=membership, role=role, scope=scope,
        active_from=active_from or timezone.now(), active_until=active_until,
        include_descendants=include_descendants,
    )
    assignment.full_clean()
    for action in {"role.manage", *role.permissions}:
        if not can_delegate(
            actor, action, scope, active_from=assignment.active_from,
            active_until=assignment.active_until, include_descendants=include_descendants,
        ):
            raise PermissionDenied("Delegation cannot exceed the actor's actions, scope, or grant duration.")
    assignment.save()
    record_event(scope.organization, actor, "role.assigned", "RoleAssignment", assignment.pk,
                 metadata={"scope_id": str(scope.pk), "membership_id": str(membership.pk), "role_id": str(role.pk)})
    return assignment


@transaction.atomic
def revoke_role(*, actor, assignment):
    # Use the persisted assignment, not caller-supplied scope/date attributes.
    assignment = RoleAssignment.objects.select_for_update().get(pk=assignment.pk)
    require_permission(actor, "role.manage", assignment.scope)
    if assignment.revoked_at is not None:
        return assignment
    assignment.revoked_at = timezone.now()
    assignment.save()
    record_event(assignment.scope.organization, actor, "role.revoked", "RoleAssignment", assignment.pk,
                 metadata={"scope_id": str(assignment.scope_id), "membership_id": str(assignment.membership_id),
                           "role_id": str(assignment.role_id)})
    return assignment
