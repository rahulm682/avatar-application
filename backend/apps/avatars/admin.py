from django.contrib import admin, messages

from . import services
from .models import Avatar


@admin.register(Avatar)
class AvatarAdmin(admin.ModelAdmin):
    """Moderation: an admin can remove, restore, or permanently delete a picture.

    "Delete" here is a SOFT delete (the picture is hidden, and removed for good after the retention period).
    Deleting a picture that is already soft-deleted, or using "Delete permanently", removes it immediately.
    """

    list_display = ("id", "user", "width", "height", "size_bytes", "is_deleted", "created_at")
    list_filter = ("is_deleted",)
    search_fields = ("user__email", "id")
    readonly_fields = [f.name for f in Avatar._meta.fields]
    ordering = ("-created_at",)
    actions = ["restore_pictures", "delete_permanently"]

    def get_queryset(self, request):
        queryset = Avatar.all_objects.select_related("user")  # includes soft-deleted pictures
        ordering = self.get_ordering(request)
        return queryset.order_by(*ordering) if ordering else queryset

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def _remove(self, avatar):
        if avatar.is_deleted:
            services.purge_avatar(avatar)
        else:
            services.delete_avatar(avatar)

    def delete_model(self, request, obj):
        self._remove(obj)

    def delete_queryset(self, request, queryset):
        for avatar in queryset:
            self._remove(avatar)

    @admin.action(description="Restore the selected pictures")
    def restore_pictures(self, request, queryset):
        restored = 0
        for avatar in queryset.filter(is_deleted=True):
            try:
                services.restore_avatar(avatar)
                restored += 1
            except services.AvatarError as exc:
                self.message_user(request, f"{avatar.pk}: {exc.message}", level=messages.ERROR)
        self.message_user(request, f"Restored {restored} picture(s).")

    @admin.action(description="Delete the selected pictures permanently (files included)", permissions=["delete"])
    def delete_permanently(self, request, queryset):
        count = 0
        for avatar in queryset:
            services.purge_avatar(avatar)
            count += 1
        self.message_user(request, f"Permanently deleted {count} picture(s).")