"""Report di sola lettura delle TrainingRequirementRule scoped per Area aziendale.

Con l'inversione gerarchia Reparto/AreaAziendale (0080) e il collegamento del
dipendente alla nuova AreaAziendale (0082), le regole di obbligo formativo per
area tornano operative ma ripartono da zero: nessun dipendente ha ancora
un'Area aziendale assegnata finché non viene riassegnata da UI. Questo comando
elenca le regole attive scoped per area e quanti dipendenti risultano oggi
assegnati a quell'area, per dare visibilità su cosa aspetta una riassegnazione.

Esempio:
    python manage.py report_regole_formazione_area
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from anagrafica.models import DipendenteAnagraficaAziendale
from anagrafica.models_formazione import TrainingRequirementRule


class Command(BaseCommand):
    help = "Sola lettura: elenca le TrainingRequirementRule per Area aziendale e i dipendenti oggi assegnati."

    def handle(self, *args, **options):
        regole = (
            TrainingRequirementRule.objects
            .filter(is_active=True, area__isnull=False)
            .select_related("area", "area__reparto", "corso", "piano")
            .order_by("area__nome")
        )
        if not regole.exists():
            self.stdout.write("Nessuna regola di formazione con target 'area aziendale' attiva.")
            return

        self.stdout.write(f"{'Area':<20} {'Reparto':<20} {'Corso/Piano':<40} {'Dipendenti assegnati':>22}")
        self.stdout.write("-" * 104)
        for regola in regole:
            oggetto = regola.corso.titolo if regola.corso_id else (regola.piano.nome if regola.piano_id else "—")
            n_dipendenti = DipendenteAnagraficaAziendale.objects.filter(area_aziendale_id=regola.area_id).count()
            reparto_nome = regola.area.reparto.nome if regola.area.reparto_id else "—"
            self.stdout.write(
                f"{regola.area.nome:<20} {reparto_nome:<20} {oggetto:<40} {n_dipendenti:>22}"
            )
