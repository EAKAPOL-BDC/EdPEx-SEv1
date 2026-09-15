from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path
from apps.accounts import web
from apps.catalog import web as catalog_web
from apps.selfassessments import web as self_web, api as self_api

urlpatterns = [
    path("", web.home, name="home"),
    path("login/", auth_views.LoginView.as_view(template_name="portal/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("language/", web.language, name="portal-language"),
    path("workspace/", web.workspace, name="workspace"),
    path("workspace/<uuid:scope_id>/members/", web.members, name="portal-members"),
    path("workspace/<uuid:scope_id>/grants/<uuid:assignment_id>/revoke/", web.revoke, name="portal-revoke"),
    path("workspace/<uuid:scope_id>/catalog/", catalog_web.catalog, name="portal-catalog"),
    path("workspace/<uuid:scope_id>/catalog/<uuid:version_id>/", catalog_web.version_detail, name="portal-catalog-detail"),
    path("workspace/self-assessments/", self_web.mine, name="self-assessment-list"),
    path("workspace/self-assessments/<uuid:assignment_id>/", self_web.detail, name="self-assessment-detail"),
    path("api/v1/me/self-assessments/", self_api.mine),
    path("api/v1/me/self-assessments/<uuid:assignment_id>/", self_api.own_schema),
    path("api/v1/me/self-assessments/<uuid:assignment_id>/draft/", self_api.draft),
    path("api/v1/me/self-assessments/<uuid:assignment_id>/submit/", self_api.submit),
    path("api/v1/self-assessment-assignments/", self_api.assign),
    path("api/v1/round-instruments/<uuid:round_instrument_id>/calculate/", self_api.calculate),
    path("api/v1/calculation-runs/<uuid:run_id>/review-request/", self_api.review_request),
    path("api/v1/calculation-runs/<uuid:run_id>/review/", self_api.review_packet),
    path("api/v1/calculation-runs/<uuid:run_id>/decision/", self_api.review_decision),
    path("admin/", admin.site.urls),
]
