from django.core.management.base import BaseCommand, CommandError
from automazioni.assenze_flow_merge import merge_flows


class Command(BaseCommand):
    help = "Unisce i due flussi Assenze censiti; conserva gli originali disattivati. Anteprima predefinita."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--workers-stopped", action="store_true")

    def handle(self, *args, **options):
        if options["apply"] and not options["workers_stopped"]:
            raise CommandError("Fermare anche il processore eventi Windows; indicare --workers-stopped.")
        try:
            result = merge_flows(apply=options["apply"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"{'APPLICATO' if options['apply'] else 'ANTEPRIMA'}: {result}")
