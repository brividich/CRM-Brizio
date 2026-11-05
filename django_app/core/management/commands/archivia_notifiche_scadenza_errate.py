"""Archivia le notifiche di scadenza create con il numero di anagrafica al posto dell'utente.

Fino al 05/11/2026 i promemoria di visite e formazione passavano a ``invia_notifica``
l'id anagrafica, quindi la notifica finiva su un altro account o su nessuno. Non cancella
nulla: archivia, la riga resta come traccia. Senza ``--apply`` conta e basta; stampa solo numeri.
"""
from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

TIPI = ("visita_scadenza", "formazione_scadenza", "formazione_promemoria")


class Command(BaseCommand):
    help = "Archivia le notifiche di scadenza consegnate all'account sbagliato (non cancella)."

    def add_arguments(self, parser):
        parser.add_argument("--fino-al", required=True, help="Ultimo giorno da trattare, AAAA-MM-GG: il giorno prima del deploy della correzione.")
        parser.add_argument("--apply", action="store_true", help="Archivia davvero. Senza, solo il conteggio.")

    def handle(self, *args, **options):
        from core.legacy_models import AnagraficaDipendente
        from core.models import Notifica

        try:
            fino_al = datetime.strptime(options["fino_al"], "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError("--fino-al deve essere AAAA-MM-GG.") from exc

        utente_di = dict(AnagraficaDipendente.objects.values_list("id", "utente_id"))
        qs = Notifica.objects.filter(tipo__in=TIPI, archiviata=False, created_at__date__lte=fino_al)
        righe = list(qs.values_list("pk", "legacy_user_id", "letta"))
        # Giusta solo se il numero di anagrafica coincide con l'utente della stessa persona.
        errate = [r for r in righe if utente_di.get(r[1]) != r[1]]
        lette = sum(1 for r in errate if r[2])
        self.stdout.write(f"Notifiche esaminate: {len(righe)}")
        self.stdout.write(f"Da archiviare: {len(errate)} (già lette: {lette}), account coinvolti: {len({r[1] for r in errate})}")
        self.stdout.write(f"Lasciate come sono: {len(righe) - len(errate)}")
        if not options["apply"]:
            self.stdout.write("Prova: nessuna modifica. Con --apply archivia.")
            return
        adesso = timezone.now()
        with transaction.atomic():
            for inizio in range(0, len(errate), 500):
                Notifica.objects.filter(pk__in=[r[0] for r in errate[inizio:inizio + 500]]).update(
                    archiviata=True, archiviata_il=adesso, archiviata_motivo="admin")
        self.stdout.write(self.style.SUCCESS(f"Archiviate: {len(errate)}"))
