from unittest.mock import patch
from django.test import SimpleTestCase,RequestFactory,override_settings
from django.http import HttpResponse
from apps.surveys.web import public_page

class SurveyHTTPGuards(SimpleTestCase):
    @override_settings(ALLOWED_HOSTS=['*'])
    def test_http_is_loopback_only_including_ipv6(self):
        view=public_page(lambda request:HttpResponse('ok'))
        cases=[('localhost','127.0.0.1',200),('[::1]','::1',200),('[2001:db8::1]','::1',400),('localhost','203.0.113.5',400),('testserver','127.0.0.1',400),('survey.example','203.0.113.5',400)]
        for host,ip,expected in cases:
            request=RequestFactory().get('/',HTTP_HOST=host,REMOTE_ADDR=ip)
            self.assertEqual(view(request).status_code,expected,(host,ip))
        self.assertEqual(view(RequestFactory().get('/',secure=True,HTTP_HOST='survey.example')).status_code,200)

    @override_settings(DEBUG=True,ALLOWED_HOSTS=['localhost'])
    def test_debug_exceptions_do_not_expose_body_or_secrets(self):
        def failing(request):raise ValueError('SECRET_FAULT_MARKER')
        response=public_page(failing)(RequestFactory().get('/',HTTP_HOST='localhost',REMOTE_ADDR='127.0.0.1'))
        self.assertEqual(response.status_code,503)
        self.assertNotIn(b'SECRET_FAULT_MARKER',response.content)
        self.assertIn('no-store',response['Cache-Control'])

    @override_settings(ALLOWED_HOSTS=['localhost'], CSRF_TRUSTED_ORIGINS=[])
    def test_form_origin_and_token_are_both_required(self):
        from django.middleware.csrf import get_token
        from django.http import JsonResponse
        def form(request):
            return JsonResponse({'token': get_token(request)})
        view = public_page(form)
        factory = RequestFactory()
        for secure in (False, True):
            with self.subTest(secure=secure):
                request = factory.get('/survey/', secure=secure, HTTP_HOST='localhost', REMOTE_ADDR='127.0.0.1')
                response = view(request)
                self.assertEqual(response['Referrer-Policy'], 'same-origin')
                secret = request.META['CSRF_COOKIE']
                token = get_token(request)
                origin = ('https' if secure else 'http') + '://localhost'
                for candidate, supplied_token, expected in (
                    (origin, token, 200),
                    ('null', token, 403),
                    ('https://untrusted.example', token, 403),
                    (origin, '', 403),
                ):
                    post = factory.post('/survey/', {'csrfmiddlewaretoken': supplied_token}, secure=secure,
                                        HTTP_HOST='localhost', HTTP_ORIGIN=candidate, REMOTE_ADDR='127.0.0.1')
                    post.COOKIES['csrftoken'] = secret
                    self.assertEqual(view(post).status_code, expected, (secure, candidate, bool(supplied_token)))
