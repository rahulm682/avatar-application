from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.avatars.public_views import public_avatar
from apps.core import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", views.health),
    path("api/", include("apps.accounts.urls")),
    path("api/", include("apps.avatars.urls")),
    path("api/", include("apps.moderation.urls")),
    # Public avatar endpoint (design doc, section 9). Served through the CDN; only lowercase 64-char hex hashes match.
    re_path(r"^avatar/(?P<email_hash>[0-9a-f]{64})$", public_avatar, name="public-avatar"),
]

# API schema and interactive docs: development only.
if settings.DEBUG:
    urlpatterns += [
        path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
        path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    ]