"""Grafo dei riferimenti tra documenti SGI (fase A2): ricostruzione e report.

Per ogni revisione corrente con testo estratto (``sgi_estrai_testi``) ricostruisce i
codici SGI citati (``SgiRiferimento``). Di norma non serve: la catena di estrazione
li ricostruisce da sola a ogni nuovo testo. Serve per il primo popolamento dopo il
deploy e per il report.

Il report riporta solo numeri e codici, mai testo dei documenti: riferimenti, quota
risolta, codici citati ma inesistenti (documenti mancanti o refusi), documenti più
citati, norme esterne citate (contate a parte, non sono riferimenti SGI).

Esempi:
    python manage.py sgi_riferimenti                 # ricostruisce + report
    python manage.py sgi_riferimenti --dry-run       # solo report, nessuna scrittura
    python manage.py sgi_riferimenti --dry-run --da-file --json C:\\temp\\rif.json
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand

from procedure_refresh.models import ProcedureRevision, SgiTestoEstratto
from procedure_refresh.sgi_riferimenti import Catalogo, estrai_citazioni, norme_citate, ricostruisci


class Command(BaseCommand):
    help = "Ricostruisce i riferimenti tra documenti SGI (A2) e stampa il report."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Calcola il report senza scrivere nel DB.")
        parser.add_argument("--da-file", action="store_true", dest="da_file",
                            help="Estrae il testo dai file (sola lettura) invece di usare quello persistito.")
        parser.add_argument("--limit", type=int, default=0, help="Solo le prime N revisioni (prove).")
        parser.add_argument("--json", default="", help="Salva il report JSON in questo file (fuori dal repo).")

    def _testi(self, da_file: bool, limit: int):
        if da_file:
            from procedure_refresh.sgi_testo import estrai

            revs = (ProcedureRevision.objects.filter(is_current=True).exclude(source_path="")
                    .select_related("document").order_by("document__code"))
            if limit:
                revs = revs[:limit]
            for rev in revs:
                path = Path(rev.source_path)
                try:
                    if not path.is_file():
                        continue
                except OSError:
                    continue
                yield rev, estrai(path).testo
            return
        qs = (SgiTestoEstratto.objects.filter(revision__is_current=True)
              .select_related("revision__document").order_by("revision__document__code"))
        if limit:
            qs = qs[:limit]
        for t in qs:
            yield t.revision, t.testo

    def handle(self, *args, **opts):
        catalogo = Catalogo()
        revisioni = righe = occorrenze = risolte = 0
        mancanti: Counter = Counter()
        citati: Counter = Counter()
        norme: Counter = Counter()
        per_tipo: Counter = Counter()
        famiglie: Counter = Counter()
        for rev, testo in self._testi(opts["da_file"], opts["limit"]):
            revisioni += 1
            norme.update(norme_citate(testo))
            documenti_citati = set()
            codici_mancanti = set()
            famiglie_citate = set()
            for c in estrai_citazioni(testo, rev.document.code):
                esito = catalogo.dettaglio(c.codice)
                doc = esito.documento
                if doc is not None and doc.pk == rev.document_id:
                    continue
                righe += 1
                occorrenze += c.occorrenze
                per_tipo[esito.tipo or "non_risolto"] += 1
                if not esito.risolto:
                    codici_mancanti.add(c.codice)
                    continue
                risolte += 1
                if doc is not None:
                    documenti_citati.add(doc.code)
                else:
                    famiglie_citate.add(c.codice)
            mancanti.update(codici_mancanti)
            citati.update(documenti_citati)
            famiglie.update(famiglie_citate)
            if not opts["dry_run"]:
                ricostruisci(rev, testo, catalogo=catalogo)

        report = {
            "revisioni_lette": revisioni,
            "riferimenti": righe,
            "occorrenze": occorrenze,
            "risolti": risolte,
            "quota_risolti": round(risolte / righe, 3) if righe else 0.0,
            "risolti_per_tipo": dict(per_tipo),
            "famiglie_citate": [{"codice": c, "revisioni_che_citano": n} for c, n in famiglie.most_common()],
            "codici_inesistenti_distinti": len(mancanti),
            "top15_codici_inesistenti": [{"codice": c, "revisioni_che_citano": n} for c, n in mancanti.most_common(15)],
            "top10_documenti_citati": [{"codice": c, "revisioni_che_citano": n} for c, n in citati.most_common(10)],
            "norme_esterne_occorrenze": sum(norme.values()),
            "norme_esterne_distinte": len(norme),
            "scritto": not opts["dry_run"],
        }
        if opts["json"]:
            Path(opts["json"]).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
