from django.core.management.base import BaseCommand

from monitoring.models import AutomationExecution, Issue


class Command(BaseCommand):
    help = "Riepilogo rapido del monitoring su stdout."

    def handle(self, *args, **options):
        open_issues = Issue.objects.filter(status__in=[Issue.Status.NEW, Issue.Status.TRIAGE, Issue.Status.IN_PROGRESS]).count()
        critical_issues = Issue.objects.filter(
            status__in=[Issue.Status.NEW, Issue.Status.TRIAGE, Issue.Status.IN_PROGRESS],
            severity=Issue.Severity.CRITICAL,
        ).count()
        failed_runs = AutomationExecution.objects.filter(status=AutomationExecution.Status.FAILED).count()
        self.stdout.write(
            f"Issue aperte: {open_issues} | Issue critiche: {critical_issues} | Run fallite: {failed_runs}"
        )
