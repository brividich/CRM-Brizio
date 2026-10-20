"""Confronto tra le fonti dell'inventario software (sola lettura).

Per i PC visti da due fonti (es. WatchGuard e Defender) elenca i prodotti che compaiono
con una sola delle due: sono i software che NON si sono fusi in una riga, di solito perché
le fonti li chiamano in modo diverso ('microsoft 365 apps' / 'microsoft 365 apps for
enterprise - it-it'). Per ognuno propone il nome più simile dell'altra fonte: se è lo
stesso prodotto, si aggiunge l'alias da 'Inventario software -> Alias' e al prossimo import
le righe si fondono. Non scrive nulla.

    manage.py software_fonti_confronto
    manage.py software_fonti_confronto --a watchguard --b defender --soglia 0.8 --max 40
"""
from __future__ import annotations

from collections import defaultdict
from difflib import SequenceMatcher

from django.core.management.base import BaseCommand, CommandError

from security.models import SoftwareInstallation, SoftwareSourceKind
from security.services.software_inventory import somiglianza_prodotti


def somiglianza(a: str, b: str) -> float:
    """Somiglianza dei nomi: rapporto tra stringhe, ma un nome contenuto per intero nell'altro vale 0.9
    ('microsoft 365 apps' in 'microsoft 365 apps for enterprise')."""
    ta, tb = a.split(), b.split()
    punteggio = SequenceMatcher(None, a, b).ratio()
    if min(len(ta), len(tb)) >= 2 and (set(ta) <= set(tb) or set(tb) <= set(ta)):
        punteggio = max(punteggio, 0.9)
    return punteggio


def confronta(fonte_a: str, fonte_b: str, *, soglia: float = 0.8):
    """Ritorna (pc_comuni, in_comune, solo_a, solo_b, proposte) sui PC visti da entrambe le fonti."""
    per_host = defaultdict(lambda: defaultdict(set))  # host -> fonte -> {(vendor, prodotto)}
    for host, vendor, product, fonti, origine in SoftwareInstallation.objects.filter(still_detected=True).exclude(
        source_kind=SoftwareSourceKind.SNMP_FIRMWARE
    ).values_list("host", "vendor", "product", "fonti", "source_kind"):
        for fonte in (fonti or [origine]):
            per_host[host][fonte].add((vendor, product))
    comuni = [h for h, f in per_host.items() if fonte_a in f and fonte_b in f]
    in_comune, solo_a, solo_b = defaultdict(int), defaultdict(int), defaultdict(int)
    for host in comuni:
        a, b = per_host[host][fonte_a], per_host[host][fonte_b]
        for chiave in a & b:
            in_comune[chiave] += 1
        for chiave in a - b:
            solo_a[chiave] += 1
        for chiave in b - a:
            solo_b[chiave] += 1
    proposte = []
    for chiave_a, n in sorted(solo_a.items(), key=lambda kv: -kv[1]):
        migliore, punteggio = None, 0.0
        for chiave_b in solo_b:
            p = max(somiglianza_prodotti(chiave_a[0], chiave_a[1], chiave_b[0], chiave_b[1]), somiglianza(chiave_a[1], chiave_b[1]))
            if chiave_a[0] and chiave_b[0] and chiave_a[0] != chiave_b[0]:
                p *= 0.9  # produttori diversi: meno probabile che sia lo stesso prodotto
            if p > punteggio:
                migliore, punteggio = chiave_b, p
        if migliore is not None and punteggio >= soglia:
            proposte.append((chiave_a, n, migliore, solo_b[migliore], punteggio))
    return len(comuni), in_comune, solo_a, solo_b, proposte


class Command(BaseCommand):
    help = "Confronta due fonti dell'inventario software sui PC che hanno in comune (sola lettura)."

    def add_arguments(self, parser):
        parser.add_argument("--a", default=SoftwareSourceKind.WATCHGUARD, help="Prima fonte (default watchguard).")
        parser.add_argument("--b", default=SoftwareSourceKind.DEFENDER, help="Seconda fonte (default defender).")
        parser.add_argument("--soglia", type=float, default=0.8, help="Somiglianza minima dei nomi per proporre un alias (0-1).")
        parser.add_argument("--max", type=int, default=30, help="Righe massime per elenco.")

    def handle(self, *args, **opts):
        validi = {k for k, _ in SoftwareSourceKind.choices}
        a, b = str(opts["a"]), str(opts["b"])
        if a not in validi or b not in validi or a == b:
            raise CommandError(f"Fonti ammesse: {', '.join(sorted(validi))} (due diverse).")
        pc, comuni, solo_a, solo_b, proposte = confronta(a, b, soglia=float(opts["soglia"]))
        limite = max(1, int(opts["max"]))
        self.stdout.write(f"PC visti da entrambe le fonti ({a} e {b}): {pc}")
        if not pc:
            self.stdout.write("Nessun PC in comune: importa prima anche l'altra fonte.")
            return
        self.stdout.write(f"Prodotti fusi in una riga: {len(comuni)} | solo {a}: {len(solo_a)} | solo {b}: {len(solo_b)}")
        if proposte:
            self.stdout.write(f"\nAlias proposti (somiglianza >= {opts['soglia']:.2f}): stesso prodotto con nomi diversi?")
            for (va, pa), na, (vb, pb), nb, p in proposte[:limite]:
                self.stdout.write(f"  [{na} PC] {a}: '{pa}' ({va or 'n/d'})  ~  [{nb} PC] {b}: '{pb}' ({vb or 'n/d'})  [{p:.2f}]")
        for nome, elenco in ((a, solo_a), (b, solo_b)):
            self.stdout.write(f"\nSolo {nome} (primi {limite}):")
            for (vendor, product), n in sorted(elenco.items(), key=lambda kv: -kv[1])[:limite]:
                self.stdout.write(f"  [{n} PC] '{product}' ({vendor or 'n/d'})")
