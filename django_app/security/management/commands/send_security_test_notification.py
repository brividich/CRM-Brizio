"""Send a synthetic test notification through a configured channel.

Lets an operator prove that email/Teams delivery actually works, without waiting for a
real critical alert. Uses a synthetic payload only: no real alert data is sent.

    python manage.py send_security_test_notification --channel "SOC email"
    python manage.py send_security_test_notification --list
"""
from django.core.management.base import BaseCommand, CommandError

from security.models import SecurityNotificationChannel, SecurityNotificationLog, Severity
from security.services import notifications


class Command(BaseCommand):
    help = "Send a synthetic test notification through a Security Center notification channel"

    def add_arguments(self, parser):
        parser.add_argument("--channel", help="Channel name (exact)")
        parser.add_argument("--list", action="store_true", help="List configured channels and exit")

    def handle(self, *args, **options):
        if options["list"]:
            for channel in SecurityNotificationChannel.objects.order_by("channel_type", "name"):
                state = "enabled" if channel.enabled else "disabled"
                self.stdout.write(
                    f"{channel.name} [{channel.channel_type}, {state}, min={channel.severity_min}, "
                    f"cooldown={channel.cooldown_minutes}m]"
                )
            return

        name = options.get("channel")
        if not name:
            raise CommandError("Provide --channel NAME (or --list to see the configured channels)")

        try:
            channel = SecurityNotificationChannel.objects.get(name=name)
        except SecurityNotificationChannel.DoesNotExist:
            raise CommandError(f"No notification channel named {name!r}. Use --list.")

        if not channel.enabled:
            self.stdout.write(self.style.WARNING(f"Channel {channel.name} is disabled; sending anyway as a test."))

        log = notifications._deliver_to_channel(
            channel,
            event_kind="test_notification",
            severity=Severity.CRITICAL,
            dedup_hash="",  # empty: never suppressed by cooldown
            subject="[Security Center] Test notification",
            body=(
                "This is a synthetic test message from Security Center.\n"
                "If you can read it, this channel can deliver critical alerts.\n"
                "No real alert data is included."
            ),
            alert=None,
            ticket=None,
        )

        if log.outcome == SecurityNotificationLog.Outcome.SENT:
            self.stdout.write(self.style.SUCCESS(f"Sent through {channel.name} ({channel.channel_type})."))
        else:
            raise CommandError(f"Delivery {log.outcome}: {log.error_message or 'no detail'}")
