from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import purge_user
from apps.avatars.models import Avatar
from apps.avatars.services import purge_avatar


class Command(BaseCommand):
    help = (
        "Permanently remove soft-deleted pictures and accounts once the retention period is over "
        "(files in S3 included)."
    )

    def add_arguments(self, parser):
        default_days = getattr(settings, "SOFT_DELETE_RETENTION_DAYS", 30)
        parser.add_argument("--days", type=int, default=default_days, help="Retention in days (default: %(default)s).")
        parser.add_argument("--dry-run", action="store_true", help="Only report what would be removed.")

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        avatars = list(Avatar.all_objects.filter(is_deleted=True, deleted_at__lt=cutoff).select_related("user"))
        users = list(User.all_objects.filter(is_deleted=True, deleted_at__lt=cutoff))

        if options["dry_run"]:
            self.stdout.write(f"Would remove {len(avatars)} picture(s) and {len(users)} account(s).")
            return

        for avatar in avatars:  # pictures first: some belong to accounts that are purged below
            purge_avatar(avatar)
        for user in users:
            purge_user(user)
        self.stdout.write(
            f"Removed {len(avatars)} picture(s) and {len(users)} account(s) deleted more than {options['days']} days ago."
        )