"""Semina/aggiorna la mappatura Cliente -> cartella share dai percorsi REALI delle specifiche.

Per ogni cliente, guarda in quali cartelle (1o livello) stanno davvero i suoi PDF collegati
(``percorso_esterno``) e propone la cartella piu' frequente. DRY-RUN di default: mostra le
proposte (il "check di conferma"); ``--apply`` le salva in ``ClienteCartellaShare``.

I clienti ambigui (file in piu' cartelle diverse) sono evidenziati con il dettaglio, cosi' si
decide a mano. Per i clienti NUOVI (senza file) usare la ricerca ``cartelle_cliente.suggerisci``
al momento della creazione (conferma in UI/admin).
"""
from __future__ import annotations

from collections import Counter, defaultdict

from django.core.management.base import BaseCommand

from gestione_specifiche.cartelle_cliente import salva_mappatura
from gestione_specifiche.models import Specifica
from gestione_specifiche.share_write import cartella_top_da_percorso


def _ascii(s: str) -> str:
    return (s or "").encode("ascii", "replace").decode("ascii")


class Command(BaseCommand):
    help = ("Semina la mappatura cliente->cartella share dai percorsi reali delle specifiche "
            "(dry-run di default; --apply per salvare).")

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="salva le mappature (default: dry-run)")

    def handle(self, *args, **opts):
        conteggi: dict[str, Counter] = defaultdict(Counter)
        for spec in Specifica.objects.filter(percorso_esterno__gt="").only("cliente", "percorso_esterno"):
            cli = (spec.cliente or "").strip()
            cart = cartella_top_da_percorso(spec.percorso_esterno)
            if cli and cart:
                conteggi[cli][cart] += 1

        creati = aggiornati = ambigui = 0
        for cli in sorted(conteggi):
            cnt = conteggi[cli]
            cartella, n = cnt.most_common(1)[0]
            ambiguo = len(cnt) > 1
            nota = "" if not ambiguo else "ambiguo: " + ", ".join(f"{k}={v}" for k, v in cnt.most_common())
            if ambiguo:
                ambigui += 1
            riga = f"  {_ascii(cli)} -> {_ascii(cartella)} ({n})"
            self.stdout.write(riga + (self.style.WARNING("  [" + _ascii(nota) + "]") if ambiguo else ""))
            if opts["apply"]:
                obj = salva_mappatura(cli, cartella, note=nota)
                if obj.created_at == obj.updated_at:
                    creati += 1
                else:
                    aggiornati += 1

        modo = "APPLY" if opts["apply"] else "DRY-RUN"
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"[{modo}] clienti: {len(conteggi)} | ambigui: {ambigui}"
            + (f" | creati: {creati} | aggiornati: {aggiornati}" if opts["apply"] else "")))
        if not opts["apply"] and conteggi:
            self.stdout.write("  (dry-run: nessun salvataggio. Verifica gli 'ambigui', poi --apply.)")
