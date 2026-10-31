from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Delete sign-ups that were never verified (design doc, section 6.2)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=settings.UNVERIFIED_ACCOUNT_TTL_HOURS,
            help="Delete unverified accounts older than this many hours (default: %(default)s).",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=options["hours"])
        stale = User.objects.filter(email_verified_at__isnull=True, is_staff=False, created_at__lt=cutoff)
        deleted, _ = stale.delete()
        self.stdout.write(f"Deleted {deleted} unverified account(s) older than {options['hours']} hours.")