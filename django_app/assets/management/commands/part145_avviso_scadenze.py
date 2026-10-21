"""Avviso settimanale delle scadenze PART 145 a Qualità.

Scadenze entro 90 giorni (e già scadute) del Dossier PART 145: contratto e requisiti dei
processi, processi, tarature/manutenzioni delle attrezzature, certificazioni del personale.
Destinatari: gli stessi dei timbri sospesi MOD.128 (``mpq_msm_reminder_emails``).

Uso:
    python manage.py part145_avviso_scadenze [--dry-run] [--recipients a@b.it ...]
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Mail a Qualità con le scadenze PART 145 entro 90 giorni (e già scadute)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Mostra le scadenze senza inviare.")
        parser.add_argument("--recipients", nargs="*", help="Destinatari al posto di quelli configurati.")

    def handle(self, *args, **opts):
        from assets.services import part145_dossier

        if opts["dry_run"]:
            dati = part145_dossier.costruisci(con_personale=True, con_audit=True, con_nc=True)
            scadenze = next(s for s in dati["sezioni"] if s.codice == "scadenze")
            for riga in scadenze.righe:
                self.stdout.write(" · ".join(str(v) for v in riga))
            self.stdout.write(f"{len(scadenze.righe)} scadenze (nessuna mail inviata).")
            return
        inviate = part145_dossier.notifica_scadenze(override=opts.get("recipients") or None)
        self.stdout.write(f"Mail inviate: {inviate or 0}")
