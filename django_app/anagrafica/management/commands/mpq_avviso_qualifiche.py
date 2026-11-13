"""Avviso settimanale a Qualità: persone e macchine qualificate da sistemare (MOD.128).

Persone non qualificate o con scadenza entro 60 giorni, macchine non operative o in
scadenza, per i processi attivi. Destinatari: quelli dei timbri sospesi MOD.128.

Uso:
    python manage.py mpq_avviso_qualifiche [--dry-run] [--recipients a@b.it ...]
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Mail a Qualità con persone e macchine qualificate (MOD.128) da sistemare."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Mostra l'elenco senza inviare.")
        parser.add_argument("--recipients", nargs="*", help="Destinatari al posto di quelli configurati.")

    def handle(self, *args, **opts):
        from anagrafica.services import mpq_scadenze

        if opts["dry_run"]:
            dati = mpq_scadenze.raccogli()
            for r in dati["persone"]:
                ab = r["abilitazione"]
                self.stdout.write(f"Persona #{ab.legacy_anagrafica_id or ab.nominativo_esterno} · "
                                  f"{r['processo'].nome} · {r['stato']['label']}")
            for r in dati["macchine"]:
                qm = r["qualifica"]
                self.stdout.write(f"Macchina {qm.asset.asset_tag} · {qm.processo.nome} · {r['stato']['label']}")
            self.stdout.write(f"{len(dati['persone'])} persone, {len(dati['macchine'])} macchine (nessuna mail).")
            return
        inviate = mpq_scadenze.notifica_scadenze(override=opts.get("recipients") or None)
        self.stdout.write(f"Mail inviate: {inviate or 0}")
