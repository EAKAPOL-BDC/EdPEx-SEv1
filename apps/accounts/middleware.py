from django.conf import settings
from django.utils import translation
from django.utils.cache import patch_vary_headers
from .models import UserPreference


class PortalLanguageMiddleware:
    """Explicit preference/cookie, then Thai; never infer a new organization or grant."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        locale = None
        if request.user.is_authenticated:
            locale = UserPreference.objects.filter(user=request.user).values_list('preferred_locale', flat=True).first()
        locale = locale or request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME, 'th')
        if locale not in {'th', 'en'}:
            locale = 'th'
        with translation.override(locale):
            request.LANGUAGE_CODE = locale
            response = self.get_response(request)
            response["Content-Language"] = locale
            patch_vary_headers(response, ("Cookie",))
            return response
