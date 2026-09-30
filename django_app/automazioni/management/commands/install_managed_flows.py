from django.core.management.base import BaseCommand
from automazioni.managed_flows import catalog, install_flows, synchronize_schedule
from automazioni.models import ManagedFlow


class Command(BaseCommand):
    help = "Converte i processi nativi in flussi del designer, senza riscrivere personalizzazioni."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if not options["apply"]:
            self.stdout.write(f"Anteprima: {len(catalog())} processi disponibili; nessuna modifica.")
            return
        created = install_flows()
        for binding in ManagedFlow.objects.select_related("rule").filter(kind="schedule"):
            synchronize_schedule(binding)
        self.stdout.write(self.style.SUCCESS(f"Flussi creati: {created}. Pianificazioni riallineate."))
