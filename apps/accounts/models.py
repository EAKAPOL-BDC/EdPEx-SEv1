"""Keep Django's existing auth.User and add scoped, revocable role grants."""

import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


ALLOWED_PERMISSIONS = frozenset({
    "catalog.read", "catalog.edit", "catalog.publish", "catalog.archive", "translation.review",
    "calendar.manage", "round.manage", "population.manage",
    "responsibility.manage", "source.manage", "audit.read", "self.read",
    "self.write", "role.manage",
})


def validate_permissions(value):
    if not isinstance(value, list) or any(
        not isinstance(action, str) or action not in ALLOWED_PERMISSIONS
        for action in value
    ):
        raise ValidationError("Permissions must be a list of explicitly supported actions.")
    if len(set(value)) != len(value):
        raise ValidationError("Duplicate permission actions are not allowed.")


def validate_timezone(value):
    try:
        ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValidationError("Use a valid IANA timezone name.") from None


class ValidatedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Organization(ValidatedModel):
    name = models.CharField(max_length=255)
    timezone = models.CharField(
        max_length=64, default="Asia/Bangkok", validators=[validate_timezone]
    )

    def __str__(self):
        return self.name


class AccessScope(ValidatedModel):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    code = models.CharField(max_length=100)
    name = models.CharField(max_length=255)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"], name="scope_org_code_unique"),
            models.CheckConstraint(condition=~models.Q(id=models.F("parent")), name="scope_not_own_parent"),
        ]

    def clean(self):
        super().clean()
        original_org = type(self).objects.filter(pk=self.pk).values_list("organization_id", flat=True).first()
        if original_org and original_org != self.organization_id:
            raise ValidationError({"organization": "An existing scope cannot move between organizations."})
        parent_id = self.parent_id
        visited = {self.pk}
        while parent_id:
            if parent_id in visited:
                raise ValidationError({"parent": "Scope parents must not form a cycle."})
            visited.add(parent_id)
            parent = type(self).objects.filter(pk=parent_id).values("organization_id", "parent_id").first()
            if parent is None:
                raise ValidationError({"parent": "Parent scope must already exist."})
            if parent["organization_id"] != self.organization_id:
                raise ValidationError({"parent": "Parent scope must belong to the same organization."})
            parent_id = parent["parent_id"]

    def __str__(self):
        return self.code


class Membership(ValidatedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "organization"], name="membership_user_org_unique"),
        ]

    def clean(self):
        super().clean()
        original = type(self).objects.filter(pk=self.pk).values("user_id", "organization_id").first()
        if original and (original["user_id"] != self.user_id or original["organization_id"] != self.organization_id):
            raise ValidationError("Membership identity cannot change; revoke it and create a new membership.")


class Role(ValidatedModel):
    code = models.CharField(max_length=100, unique=True)
    permissions = models.JSONField(default=list, blank=True, validators=[validate_permissions])

    def clean(self):
        super().clean()
        previous = type(self).objects.filter(pk=self.pk).first()
        if previous and previous.assignments.exists() and (
            previous.code != self.code or previous.permissions != self.permissions
        ):
            raise ValidationError("Assigned roles are immutable; create a new role and dated grant.")

    def __str__(self):
        return self.code


class RoleAssignment(ValidatedModel):
    membership = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="role_assignments")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="assignments")
    scope = models.ForeignKey(AccessScope, on_delete=models.PROTECT, related_name="role_assignments")
    active_from = models.DateTimeField(default=timezone.now)
    active_until = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True, editable=False)
    include_descendants = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(active_until__isnull=True) | models.Q(active_until__gt=models.F("active_from")),
                name="role_assignment_valid_dates",
            ),
        ]
        indexes = [models.Index(fields=["membership", "scope"], name="role_membership_scope_idx")]

    def clean(self):
        super().clean()
        previous = type(self).objects.filter(pk=self.pk).first()
        if previous:
            for field in self._meta.concrete_fields:
                if field.name not in {"updated_at", "revoked_at"} and getattr(previous, field.attname) != getattr(self, field.attname):
                    raise ValidationError("Grant history is immutable; revoke and create a new grant.")
            if previous.revoked_at is not None and previous.revoked_at != self.revoked_at:
                raise ValidationError("A recorded revocation cannot change.")
        if self.membership_id and self.scope_id:
            membership_org = Membership.objects.filter(pk=self.membership_id).values_list("organization_id", flat=True).first()
            scope_org = AccessScope.objects.filter(pk=self.scope_id).values_list("organization_id", flat=True).first()
            if membership_org and scope_org and membership_org != scope_org:
                raise ValidationError({"scope": "Grant and membership must belong to the same organization."})
        if self.active_from and timezone.is_naive(self.active_from):
            raise ValidationError({"active_from": "Use a timezone-aware datetime."})
        if self.active_until and timezone.is_naive(self.active_until):
            raise ValidationError({"active_until": "Use a timezone-aware datetime."})
        if self.active_from and self.active_until and self.active_until <= self.active_from:
            raise ValidationError({"active_until": "Grant end must follow its start."})

    def delete(self, *args, **kwargs):
        raise ValidationError("Grant history is retained; revoke the grant instead.")


class UserPreference(ValidatedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    preferred_locale = models.CharField(max_length=2, choices=[("th", "ไทย"), ("en", "English")], default="th")
