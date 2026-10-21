"""Conservazione dei dati personali negli archivi tecnici (vedi ``core/gdpr_retention.py``).

Uso:
    python manage.py gdpr_retention                 # anteprima: righe oltre il termine
    python manage.py gdpr_retention --apply         # cancella / svuota
    python manage.py gdpr_retention --solo accessi  # una sola regola
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core import gdpr_retention


class Command(BaseCommand):
    help = "Cancella o minimizza i dati personali degli archivi tecnici oltre il termine di conservazione"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Applica. Senza: solo anteprima.")
        parser.add_argument("--solo", choices=[r.codice for r in gdpr_retention.REGOLE], default=None)

    def handle(self, *args, **options):
        apply = options["apply"]
        esiti = gdpr_retention.esegui(apply=apply, solo=options["solo"])
        for e in esiti:
            stato = f"ERRORE {e['errore']}" if e["errore"] else f"{e['righe']} righe"
            self.stdout.write(f"{'[applicato]' if apply else '[anteprima]'} {e['codice']} "
                              f"(termine {e['giorni']} giorni): {stato}")
        if not apply:
            self.stdout.write("Anteprima: nulla e' stato modificato. Rilancia con --apply.")
        errori = [e for e in esiti if e["errore"]]
        if errori:
            raise CommandError(f"{len(errori)} regole non eseguite: vedi sopra.")
