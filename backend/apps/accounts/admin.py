from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils import timezone

from apps.core.cdn import invalidate_email_hashes

from .emailhash import hash_email
from .forms import UserChangeForm, UserCreationForm
from .models import User
from .services import RestoreError, purge_user, restore_user, soft_delete_user


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = UserChangeForm
    add_form = UserCreationForm

    ordering = ("-created_at",)
    list_display = ("email", "display_name", "email_verified_at", "is_active", "is_staff", "is_deleted", "created_at")
    list_filter = ("is_deleted", "is_active", "is_staff", "is_superuser")
    search_fields = ("email", "display_name", "email_hash")
    readonly_fields = (
        "email_hash", "current_avatar", "is_deleted", "deleted_at", "original_email", "last_login", "created_at", "updated_at",
    )
    actions = ["mark_email_verified", "restore_accounts", "delete_permanently"]

    fieldsets = (
        (None, {"fields": ("email", "email_hash", "password")}),
        ("Profile", {"fields": ("display_name", "bio", "current_avatar")}),
        ("Verification", {"fields": ("email_verified_at",)}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Deletion", {"fields": ("is_deleted", "deleted_at", "original_email")}),
        ("Dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),
    )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            return
        # What /avatar/{hash} returns can change when an admin edits these fields.
        if "email" in form.changed_data:
            invalidate_email_hashes(hash_email(form.initial.get("email", "")), obj.email_hash)
        elif {"is_active", "email_verified_at"} & set(form.changed_data):
            invalidate_email_hashes(obj.email_hash)

    def get_queryset(self, request):
        queryset = User.all_objects.all()  # includes soft-deleted accounts
        ordering = self.get_ordering(request)
        return queryset.order_by(*ordering) if ordering else queryset

    def _remove(self, user):
        """Soft delete; an account that is already soft-deleted is removed for good."""
        if user.is_deleted:
            purge_user(user)
        else:
            soft_delete_user(user)

    def delete_model(self, request, obj):
        self._remove(obj)

    def delete_queryset(self, request, queryset):
        for user in list(queryset):
            self._remove(user)

    @admin.action(description="Restore the selected deleted accounts")
    def restore_accounts(self, request, queryset):
        restored = 0
        for user in queryset.filter(is_deleted=True):
            try:
                restore_user(user)
                restored += 1
            except RestoreError as exc:
                self.message_user(request, f"{user.original_email}: {exc}", level=messages.ERROR)
        self.message_user(request, f"Restored {restored} account(s).")

    @admin.action(description="Delete the selected accounts permanently (files included)", permissions=["delete"])
    def delete_permanently(self, request, queryset):
        count = 0
        for user in list(queryset):
            purge_user(user)
            count += 1
        self.message_user(request, f"Permanently deleted {count} account(s).")

    @admin.action(description="Mark selected users' emails as verified")
    def mark_email_verified(self, request, queryset):
        updated = queryset.filter(email_verified_at__isnull=True).update(email_verified_at=timezone.now())
        self.message_user(request, f"{updated} user(s) marked as verified.")