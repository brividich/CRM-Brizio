"""Manda la scheda completa di una o più segnalazioni del Diario del preposto, formato NOVICROM HUB.

Le segnalazioni si indicano col codice (DP-2026-0012) o col numero interno.

Esempi:
    python manage.py invia_mail_preposto DP-2026-0012 --to rspp@example.com --dry-run
    python manage.py invia_mail_preposto DP-2026-0012 --to rspp@example.com --cc rls@example.com --allegati
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from diario_preposto.mail_scheda import componi, invia
from diario_preposto.models import SegnalazionePreposto
from rilevazione_incidenti.management.commands.invia_mail_segnalazione import indirizzi


def trova(riferimento: str) -> SegnalazionePreposto | None:
    rif = str(riferimento).strip()
    trovata = SegnalazionePreposto.objects.filter(codice_identificativo__iexact=rif).first()
    if trovata is None and rif.isdigit():
        trovata = SegnalazionePreposto.objects.filter(pk=int(rif)).first()
    return trovata


class Command(BaseCommand):
    help = "Manda per mail la scheda completa di una segnalazione del Diario del preposto (formato NOVICROM HUB)."

    def add_arguments(self, parser):
        parser.add_argument("riferimenti", nargs="+", help="Codice (es. DP-2026-0012) o numero interno.")
        parser.add_argument("--to", action="append", required=True, help="Destinatario (ripetibile o separato da virgola).")
        parser.add_argument("--cc", action="append", help="Copia conoscenza (ripetibile o separato da virgola).")
        parser.add_argument("--allegati", action="store_true", help="Allega i file della segnalazione (max 15 MB in tutto).")
        parser.add_argument("--dry-run", action="store_true", help="Mostra oggetto e testo senza inviare.")

    def handle(self, *args, **opts):
        to = indirizzi(opts["to"])
        cc = indirizzi(opts.get("cc"))
        if not to:
            raise CommandError("Serve almeno un destinatario in --to.")

        segnalazioni, mancanti = [], []
        for rif in opts["riferimenti"]:
            s = trova(rif)
            if s:
                segnalazioni.append(s)
            else:
                mancanti.append(rif)
        if mancanti:
            raise CommandError("Segnalazioni non trovate: " + ", ".join(mancanti))

        errori = 0
        for s in segnalazioni:
            codice = s.codice_identificativo or f"#{s.pk}"
            if opts["dry_run"]:
                mail = componi(s)
                self.stdout.write(f"--- {codice} (non inviata) a {', '.join(to)}" + (f" cc {', '.join(cc)}" if cc else ""))
                self.stdout.write(f"Oggetto: {mail['oggetto']}\n\n{mail['testo']}\n")
                continue
            try:
                inviate, esclusi = invia(s, to, cc=cc, con_allegati=opts["allegati"])
            except Exception as exc:
                errori += 1
                self.stderr.write(f"{codice}: invio non riuscito ({type(exc).__name__}: {exc})")
                continue
            if not inviate:
                errori += 1
                self.stderr.write(f"{codice}: mail non partita (disattivata o nessun destinatario accettato).")
                continue
            self.stdout.write(self.style.SUCCESS(f"{codice}: mail inviata a {', '.join(to + cc)}"))
            if esclusi:
                self.stdout.write(self.style.WARNING(f"{codice}: allegati non inclusi: {', '.join(esclusi)}"))
        if errori:
            raise CommandError(f"{errori} mail non inviate: vedi Automazioni → Mail inviate.")
