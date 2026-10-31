from django.urls import path

from . import views

urlpatterns = [
    path("avatars/", views.AvatarListView.as_view()),
    path("avatars/upload-url/", views.UploadUrlView.as_view()),
    path("avatars/confirm/", views.ConfirmUploadView.as_view()),
    path("avatars/<uuid:pk>/", views.AvatarDetailView.as_view()),
    path("me/current-avatar/", views.CurrentAvatarView.as_view()),
]