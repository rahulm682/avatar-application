from django.contrib import admin
from django.utils import timezone

from apps.accounts.authtokens import revoke_all_refresh_tokens
from apps.accounts.models import User
from apps.avatars import services
from apps.avatars.models import Avatar
from apps.core.cdn import invalidate_email_hashes

from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    """The moderation queue (design doc, section 11). Select open reports, then pick an action."""

    list_display = ("created_at", "status", "short_reason", "short_hash", "picture_still_exists")
    list_filter = ("status",)
    search_fields = ("email_hash", "reason", "avatar_uuid", "user_uuid")
    readonly_fields = ("avatar_uuid", "user_uuid", "email_hash", "reason", "created_at", "handled_at")
    ordering = ("-created_at",)
    actions = ["remove_pictures", "deactivate_users", "dismiss_reports"]

    def has_add_permission(self, request):
        return False

    @admin.display(description="Reason")
    def short_reason(self, report):
        return report.reason if len(report.reason) <= 60 else report.reason[:57] + "..."

    @admin.display(description="Hash")
    def short_hash(self, report):
        return report.email_hash[:12] + "..."

    @admin.display(description="Picture exists", boolean=True)
    def picture_still_exists(self, report):
        return Avatar.objects.filter(pk=report.avatar_uuid).exists()

    @staticmethod
    def _close(status, **match):
        """Closes every open report matching the filter. Returns how many were closed."""
        return Report.objects.filter(status=Report.Status.OPEN, **match).update(status=status, handled_at=timezone.now())

    @admin.action(description="Remove the reported pictures")
    def remove_pictures(self, request, queryset):
        removed = closed = 0
        for report in queryset.filter(status=Report.Status.OPEN):
            avatar = Avatar.objects.filter(pk=report.avatar_uuid).select_related("user").first()
            if avatar is not None:
                services.delete_avatar(avatar)  # database row, S3 files, CDN copies
                removed += 1
            closed += self._close(Report.Status.ACTIONED, avatar_uuid=report.avatar_uuid)
        self.message_user(request, f"Removed {removed} picture(s) and closed {closed} report(s).")

    @admin.action(description="Deactivate the reported users")
    def deactivate_users(self, request, queryset):
        deactivated = closed = 0
        for report in queryset.filter(status=Report.Status.OPEN):
            user = User.objects.filter(pk=report.user_uuid).first()
            if user is not None and user.is_active and not user.is_staff:  # staff are never deactivated from here
                user.is_active = False
                user.save(update_fields=["is_active", "updated_at"])
                revoke_all_refresh_tokens(user)
                invalidate_email_hashes(user.email_hash)
                deactivated += 1
            closed += self._close(Report.Status.ACTIONED, user_uuid=report.user_uuid)
        self.message_user(request, f"Deactivated {deactivated} user(s) and closed {closed} report(s).")

    @admin.action(description="Dismiss the selected reports")
    def dismiss_reports(self, request, queryset):
        count = queryset.filter(status=Report.Status.OPEN).update(
            status=Report.Status.DISMISSED, handled_at=timezone.now()
        )
        self.message_user(request, f"Dismissed {count} report(s).")