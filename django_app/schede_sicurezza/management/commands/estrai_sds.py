from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from schede_sicurezza.models import SchedaSicurezza
from schede_sicurezza.services.ingestion import estrai_sds


class Command(BaseCommand):
    help = "Rilancia l'estrazione section-aware PyMuPDF su una scheda di sicurezza esistente."

    def add_arguments(self, parser):
        parser.add_argument("scheda_id", type=int, help="ID della SchedaSicurezza da rielaborare.")

    def handle(self, *args, **options):
        scheda_id = options["scheda_id"]
        try:
            scheda = SchedaSicurezza.objects.select_related("prodotto").get(pk=scheda_id)
        except SchedaSicurezza.DoesNotExist as exc:
            raise CommandError(f"SchedaSicurezza {scheda_id} non trovata.") from exc

        estrai_sds(scheda)
        scheda.refresh_from_db()
        self.stdout.write(self.style.SUCCESS(
            f"Estrazione completata per scheda {scheda_id} ({scheda.prodotto.nome}): "
            f"stato={scheda.estrazione_stato}"
        ))
