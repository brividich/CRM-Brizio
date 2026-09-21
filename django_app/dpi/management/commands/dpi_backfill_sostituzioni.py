"""Applica retroattivamente la sostituzione automatica DPI (introdotta in
consegna_richiesta / views.py) ai duplicati già esistenti in produzione,
creati prima che quella logica esistesse.

Per ogni gruppo (dipendente, categoria, tipo_dpi) con più di una ConsegnaDPI
ancora attiva (stato CONSEGNATA, sostituita_da nullo), tiene attiva solo la
più recente per data_consegna e marca le altre come sostituite da questa,
con lo stesso commento interno automatico e la stessa voce di audit usati
dal flusso live.

Usage:
    python manage.py dpi_backfill_sostituzioni --dry-run
    python manage.py dpi_backfill_sostituzioni
"""
from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from dpi.models import ConsegnaDPI, RichiestaDPICommento, StatoRichiesta


class Command(BaseCommand):
    help = "Marca come sostituite le consegne DPI duplicate (stesso dipendente/categoria/tipo) già esistenti."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Simula senza salvare nulla.")

    def handle(self, *args, **options):
        dry_run: bool = bool(options["dry_run"])
        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna modifica verrà salvata.\n"))

        attive = (
            ConsegnaDPI.objects.filter(
                richiesta__stato=StatoRichiesta.CONSEGNATA,
                sostituita_da__isnull=True,
                richiesta__richiedente_legacy_id__isnull=False,
            )
            .select_related("richiesta")
            .order_by("richiesta__richiedente_legacy_id", "richiesta__categoria_id", "richiesta__tipo_dpi_id")
        )

        gruppi: dict[tuple, list[ConsegnaDPI]] = defaultdict(list)
        for consegna in attive:
            chiave = (
                consegna.richiesta.richiedente_legacy_id,
                consegna.richiesta.categoria_id,
                consegna.richiesta.tipo_dpi_id,
            )
            gruppi[chiave].append(consegna)

        n_gruppi_duplicati = n_sostituite = 0

        for chiave, consegne in gruppi.items():
            if len(consegne) < 2:
                continue
            n_gruppi_duplicati += 1
            consegne.sort(key=lambda c: (c.data_consegna, c.created_at), reverse=True)
            piu_recente, *vecchie = consegne

            self.stdout.write(
                f"  dipendente={chiave[0]} categoria={chiave[1]} tipo={chiave[2]}: "
                f"tiene attiva {piu_recente.richiesta.numero} ({piu_recente.data_consegna}), "
                f"sostituisce {len(vecchie)} consegna/e"
            )

            for vecchia in vecchie:
                n_sostituite += 1
                self.stdout.write(
                    f"    {'[DRY] ' if dry_run else ''}{vecchia.richiesta.numero} ({vecchia.data_consegna}) -> sostituita"
                )
                if dry_run:
                    continue
                with transaction.atomic():
                    vecchia.sostituita_da = piu_recente
                    vecchia.data_sostituzione = piu_recente.data_consegna
                    vecchia.save(update_fields=["sostituita_da", "data_sostituzione"])
                    RichiestaDPICommento.objects.create(
                        richiesta=vecchia.richiesta,
                        autore_nome="Sistema (backfill)",
                        testo=(
                            f"DPI sostituito retroattivamente dalla consegna {piu_recente.richiesta.numero} "
                            f"del {piu_recente.data_consegna.strftime('%d-%m-%Y')} "
                            f"(pulizia duplicati dpi_backfill_sostituzioni)."
                        ),
                        is_interno=True,
                    )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{'[DRY-RUN] ' if dry_run else ''}Completato: "
            f"{n_gruppi_duplicati} gruppi con duplicati, {n_sostituite} consegne marcate sostituite."
        ))
