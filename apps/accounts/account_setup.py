"""Create an ordinary account and scoped grant; no global admin flags are exposed."""
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password, password_validators_help_texts
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from apps.selfassessments.operator_web import page
from .models import Membership, Role
from .permissions import require_permission
from .services import assign_role
from apps.auditlog.services import record_event


class AccountForm(forms.Form):
    username = forms.CharField(label='ชื่อบัญชี / Username', max_length=150,
        validators=get_user_model()._meta.get_field('username').validators)
    first_name = forms.CharField(label='ชื่อ / First name', max_length=150)
    last_name = forms.CharField(label='นามสกุล / Last name', max_length=150)
    email = forms.EmailField(label='อีเมล / Email', required=False)
    password1 = forms.CharField(label='รหัสผ่านเริ่มต้น / Initial password', widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    password2 = forms.CharField(label='ยืนยันรหัสผ่าน / Confirm password', widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    role = forms.ModelChoiceField(label='บทบาทในขอบเขตนี้ / Role in this scope', queryset=Role.objects.all().order_by('code'))
    active_until = forms.DateTimeField(label='สิ้นสุดสิทธิ์ (เว้นว่างหากไม่กำหนด) / Grant expiry (optional)', required=False,
        widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].help_text = ' '.join(password_validators_help_texts())

    def clean(self):
        data = super().clean()
        if data.get('password1') != data.get('password2'):
            self.add_error('password2', 'รหัสผ่านไม่ตรงกัน / Passwords do not match.')
        if data.get('password1'):
            user = get_user_model()(**{k: data.get(k, '') for k in ('username', 'first_name', 'last_name', 'email')})
            try:
                validate_password(data['password1'], user)
            except ValidationError as exc:
                self.add_error('password1', exc)
        return data


@transaction.atomic
def create_account(actor, scope, data):
    require_permission(actor, 'role.manage', scope)
    if get_user_model().objects.filter(username=data['username']).exists():
        raise ValidationError('ชื่อบัญชีนี้ถูกใช้แล้ว / Username is already in use.')
    user = get_user_model()(**{k: data[k] for k in ('username', 'first_name', 'last_name', 'email')})
    validate_password(data['password1'], user)
    user.set_password(data['password1'])
    user.full_clean()
    user.save()
    membership = Membership.objects.create(user=user, organization=scope.organization)
    assign_role(actor=actor, scope=scope, membership=membership, role=data['role'], active_until=data.get('active_until'))
    record_event(scope.organization, actor, 'account.created', 'Membership', membership.pk,
                 metadata={'scope_id': str(scope.pk), 'membership_id': str(membership.pk)})
    return user


@sensitive_post_parameters('password1', 'password2')
@page(['GET', 'POST'])
def new_account(request, scope):
    require_permission(request.user, 'role.manage', scope)
    role = Role.objects.filter(code='self-service-v1').first()
    form = AccountForm(request.POST if request.method == 'POST' else None, initial={'role': role})
    if request.method == 'POST' and form.is_valid():
        try:
            create_account(request.user, scope, form.cleaned_data)
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'บัญชีซ้ำ กรุณาเลือกชื่อใหม่ / Duplicate username.')
        else:
            messages.success(request, 'สร้างบัญชีและมอบบทบาทแล้ว / Account and scoped role created.')
            return redirect('portal-members', scope_id=scope.pk)
    return render(request, 'portal/manage_form.html', {'scope': scope, 'form': form,
        'account_setup': True, 'title': 'สร้างบัญชีผู้ใช้งานภายใน / Create internal account',
        'notice': 'เลือกบทบาทตามงานของเจ้าหน้าที่ ผู้ตอบสาธารณะไม่ต้องมีบัญชี บทบาท self-service-v1 ใช้กับงานที่ผูกบัญชีเดิมเท่านั้น / Choose the staff role required. Public respondents need no account; self-service-v1 is for legacy account-bound work.'},
        status=422 if form.is_bound and form.errors else 200)
