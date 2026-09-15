from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path
from apps.accounts import web
from apps.catalog import web as catalog_web

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
    path("admin/", admin.site.urls),
]
