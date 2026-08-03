"""Promemoria in-app ai responsabili con task non confermati prima di una chiusura."""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from checklist_operativa.models import ChiusuraEvento, ChiusuraVoce
from core.notifiche import invia_notifica

# Soglie di preavviso: notificato solo quando i giorni residui coincidono con
# una di queste, cosi' il comando puo' girare 1x/giorno senza spammare.
_SOGLIE_GIORNI = (7, 3, 1, 0)


class Command(BaseCommand):
    help = "Invia promemoria in-app ai responsabili di task non confermati per le chiusure aziendali in arrivo."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Mostra senza inviare notifiche.")

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        oggi = timezone.localdate()

        eventi = ChiusuraEvento.objects.filter(
            stato=ChiusuraEvento.STATO_APERTA,
            data_inizio__gte=oggi,
        )

        inviati = 0
        for evento in eventi:
            giorni_residui = (evento.data_inizio - oggi).days
            if giorni_residui not in _SOGLIE_GIORNI:
                continue

            voci_da_confermare = (
                ChiusuraVoce.objects.filter(evento=evento, confermato=False, responsabile__isnull=False)
                .select_related("responsabile")
            )
            for voce in voci_da_confermare:
                messaggio = (
                    f"Checklist chiusura '{evento.nome}' ({evento.data_inizio:%d/%m/%Y}): "
                    f"manca la conferma per '{voce.descrizione[:80]}'."
                )
                self.stdout.write(
                    f"[{'DRY-RUN ' if dry_run else ''}gg={giorni_residui}] "
                    f"{voce.responsabile} -> {messaggio}"
                )
                if not dry_run and voce.responsabile.utente_id:
                    invia_notifica(
                        voce.responsabile.utente_id,
                        "generico",
                        messaggio,
                        "/checklist-operativa/",
                    )
                    inviati += 1

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna notifica inviata."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Notifiche inviate: {inviati}"))
