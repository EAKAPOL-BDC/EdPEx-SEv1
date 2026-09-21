"""Shared privacy headers, database-backed login limits and minimal health probes."""
import logging
from django.db import DatabaseError, connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.exceptions import InconsistentMigrationHistory
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils.crypto import salted_hmac
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


def database_failure_category(error):
    """Classify locally without putting raw database error text in logs."""
    text = str(error).lower()
    for category, fragments in (
        ('authentication_rejected', ('password authentication failed', 'sasl authentication failed', 'authentication failed')),
        ('pooler_project_not_found', ('tenant or user not found',)),
        ('connection_timeout', ('timeout expired', 'timed out', 'connection timeout')),
        ('dns_failure', ('could not translate host', 'name or service not known', 'getaddrinfo')),
        ('tls_failure', ('certificate verify failed', 'ssl error', 'tls')),
        ('connection_limit', ('maxclients', 'too many clients', 'remaining connection slots', 'max client connections')),
        ('network_unreachable', ('connection refused', 'network is unreachable', 'no route to host')),
    ):
        if any(fragment in text for fragment in fragments):
            return category
    return 'unclassified'


class HealthMiddleware:
    """Probe availability without sessions, user lookup or internal details."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path not in {'/health/live/', '/health/ready/'}:
            return self.get_response(request)
        if request.method not in {'GET', 'HEAD'}:
            return HttpResponse(status=405)
        ready = True
        if request.path == '/health/ready/':
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT 1 FROM accounts_accessscope LIMIT 0')
                    cursor.execute('SELECT 1 FROM calculations_calculationrun LIMIT 0')
                executor = MigrationExecutor(connection)
                executor.loader.check_consistent_history(connection)
                ready = not executor.migration_plan(executor.loader.graph.leaf_nodes())
                if not ready:
                    logger.warning('Readiness unavailable: pending migrations')
            except (DatabaseError, InconsistentMigrationHistory) as exc:
                # Log only the error class/SQLSTATE, never credentials, SQL,
                # connection strings or raw server error messages.
                cause = exc.__cause__ or exc
                state = getattr(cause, 'sqlstate', None)
                state = state if isinstance(state, str) and len(state) == 5 and state.isalnum() else 'unknown'
                logger.warning('Readiness unavailable: %s category=%s SQLSTATE=%s',
                               type(exc).__name__, database_failure_category(cause), state)
                ready = False
        response = JsonResponse({'status': 'ok' if ready else 'unavailable'}, status=200 if ready else 503)
        response['Cache-Control'] = 'no-store'
        return response


class PortalSecurityMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        # Covers the staff portal and Django administration login. CSRF middleware
        # runs first. No password, raw username, IP or invitation code is persisted.
        if request.method != 'POST' or not match or match.url_name != 'login':
            return None
        from apps.surveys.services import throttle
        username = request.POST.get('username', '').strip().casefold()[:150]
        address = request.META.get('REMOTE_ADDR', 'unknown')
        try:
            # Stop first on the client budget so rejected requests cannot create
            # unlimited account buckets by varying the submitted username.
            client_allowed = throttle(salted_hmac('nexora-login-client', address).hexdigest(), limit=300)
            account_allowed = client_allowed and throttle(salted_hmac('nexora-login-account', username).hexdigest(), limit=12)
        except DatabaseError:
            return self._problem(request, 503)
        if not account_allowed or not client_allowed:
            response = self._problem(request, 429)
            response['Retry-After'] = '600'
            return response

    @staticmethod
    def _problem(request, status):
        return render(request, 'portal/service_problem.html', {'throttled': status == 429}, status=status)

    def process_response(self, request, response):
        if ((getattr(request, 'user', None) is not None and request.user.is_authenticated)
                or request.path.startswith(('/login/', '/admin/', '/account/', '/survey/'))):
            response['Cache-Control'] = 'no-store, private'
            response['X-Robots-Tag'] = 'noindex, nofollow'
        response.setdefault('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; base-uri 'self'")
        response.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        return response

