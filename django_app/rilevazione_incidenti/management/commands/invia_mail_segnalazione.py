"""Manda la scheda completa di una o più segnalazioni di sicurezza, nel formato NOVICROM HUB.

Esempi:
    python manage.py invia_mail_segnalazione 40 --to rls@example.com --dry-run
    python manage.py invia_mail_segnalazione 40 41 --to rls@example.com --cc rspp@example.com
    python manage.py invia_mail_segnalazione 40 --to preposti@example.com --senza-nominativo
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

from rilevazione_incidenti.mail_scheda import componi, invia
from rilevazione_incidenti.models import RilevazioneIncidente


def indirizzi(valori: list[str] | None) -> list[str]:
    """Indirizzi da --to/--cc (ripetibili o separati da virgola/punto e virgola), validati."""
    elenco: list[str] = []
    for valore in valori or []:
        for parte in str(valore).replace(";", ",").split(","):
            parte = parte.strip()
            if not parte:
                continue
            try:
                validate_email(parte)
            except ValidationError as exc:
                raise CommandError(f"Indirizzo non valido: {parte}") from exc
            if parte.lower() not in {e.lower() for e in elenco}:
                elenco.append(parte)
    return elenco


class Command(BaseCommand):
    help = "Manda per mail la scheda completa di una segnalazione di sicurezza (formato NOVICROM HUB)."

    def add_arguments(self, parser):
        parser.add_argument("ids", nargs="+", type=int, help="Numero della segnalazione (es. 40).")
        parser.add_argument("--to", action="append", required=True, help="Destinatario (ripetibile o separato da virgola).")
        parser.add_argument("--cc", action="append", help="Copia conoscenza (ripetibile o separato da virgola).")
        parser.add_argument(
            "--senza-nominativo", action="store_true",
            help="Toglie nominativo e descrizione dell'avvenimento (come l'informativa a preposti e RLS).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Mostra oggetto e testo senza inviare.")

    def handle(self, *args, **opts):
        to = indirizzi(opts["to"])
        cc = indirizzi(opts.get("cc"))
        if not to:
            raise CommandError("Serve almeno un destinatario in --to.")
        con_nominativo = not opts["senza_nominativo"]

        trovate = {r.pk: r for r in RilevazioneIncidente.objects.filter(pk__in=opts["ids"])}
        mancanti = [i for i in opts["ids"] if i not in trovate]
        if mancanti:
            raise CommandError("Segnalazioni non trovate: " + ", ".join(f"#{i}" for i in mancanti))

        errori = 0
        for pk in opts["ids"]:
            r = trovate[pk]
            if opts["dry_run"]:
                mail = componi(r, con_nominativo=con_nominativo)
                self.stdout.write(f"--- #{pk} (non inviata) a {', '.join(to)}" + (f" cc {', '.join(cc)}" if cc else ""))
                self.stdout.write(f"Oggetto: {mail['oggetto']}\n\n{mail['testo']}\n")
                continue
            try:
                inviate = invia(r, to, cc=cc, con_nominativo=con_nominativo)
            except Exception as exc:
                errori += 1
                self.stderr.write(f"#{pk}: invio non riuscito ({type(exc).__name__}: {exc})")
                continue
            if inviate:
                self.stdout.write(self.style.SUCCESS(f"#{pk}: mail inviata a {', '.join(to + cc)}"))
            else:
                errori += 1
                self.stderr.write(f"#{pk}: mail non partita (disattivata o nessun destinatario accettato).")
        if errori:
            raise CommandError(f"{errori} mail non inviate: vedi Automazioni → Mail inviate.")
