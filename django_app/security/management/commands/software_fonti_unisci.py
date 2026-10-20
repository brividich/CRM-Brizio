"""Fonde nell'inventario software le righe di fonti diverse che sono lo stesso software.

Stesso PC, stessa versione, prodotto equivalente (stesso nome base senza il produttore, es.
«chrome» di Defender e «Google Chrome» di WatchGuard; oppure un nome contenuto nell'altro con
al massimo due parole in piu e senza numeri). Si tiene la riga piu vecchia, le fonti si sommano,
gli impatti CVE passano alla riga tenuta. Le coppie ambigue si saltano.

Senza --applica non scrive nulla: elenca soltanto le coppie.

    manage.py software_fonti_unisci            (anteprima)
    manage.py software_fonti_unisci --applica  (fonde davvero)
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from security.models import SoftwareInstallation
from security.services import software_inventory


class Command(BaseCommand):
    help = "Fonde le righe equivalenti di fonti diverse (anteprima senza --applica)."

    def add_arguments(self, parser):
        parser.add_argument("--applica", action="store_true", help="Fonde davvero (senza: solo anteprima).")
        parser.add_argument("--max", type=int, default=40, help="Coppie da mostrare in anteprima.")

    def handle(self, *args, **opts):
        esito = software_inventory.unisci_per_equivalenza(applica=bool(opts["applica"]))
        coppie = esito["coppie"]
        self.stdout.write(f"Coppie da fondere: {len(coppie)} | ambigue saltate: {esito['ambigue']}")
        if coppie:
            pk = {c[0] for c in coppie} | {c[1] for c in coppie}
            righe = {r.pk: r for r in SoftwareInstallation.objects.filter(pk__in=pk)} if not opts["applica"] else {}
            for tenuta, altra, fonti, punteggio in coppie[: max(1, int(opts["max"]))]:
                a, b = righe.get(tenuta), righe.get(altra)
                if a and b:
                    self.stdout.write(f"  [{punteggio:.1f}] {a.host}: '{a.product}' ({a.source_kind}) + '{b.product}' ({b.source_kind}) v{a.version_raw}")
        if opts["applica"]:
            self.stdout.write(f"Fuse: {esito['fuse']}. Ricalcola gli impatti CVE se serve (Vulnerabilita > Ricalcola).")
        elif coppie:
            self.stdout.write("Anteprima: nessuna modifica. Rilancia con --applica per fondere.")
