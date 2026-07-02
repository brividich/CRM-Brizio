"""Comando A - recupero delle specifiche importate: porta nel portale (allegato raw cifrato) il PDF
che oggi vive SOLO sulla share, ma solo per i file PRISTINI (promuovibili), abilitando F6b-2 su di essi.

Per ogni Specifica con ``percorso_esterno`` e SENZA ``allegato``:
- classifica il PDF (riuso della logica del detector F1): agisce SOLO se il documento non contiene
  marker MOD.133/cover E la prima pagina e' contenuto (raw pristino); salta gli altri (gia'
  compositati, scansioni non verificabili, irraggiungibili, protetti da password);
- legge il PDF dalla share (sola lettura, sempre via allowlist ``risolvi_consentito``);
- lo salva come ``allegato`` nello storage privato cifrato del portale (il raw), aggiorna il campo
  con ``update()`` (niente FSM) e scrive un audit ``EventoSpecifica`` (trigger=importa_raw_allegato).

NON tocca la share, NON cambia stato. DRY-RUN di default (elenca cosa promuoverebbe); ``--apply``
per eseguire. Idempotente: salta chi ha gia' un allegato.
"""
from __future__ import annotations

import os

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from gestione_specifiche.management.commands.analizza_pdf_specifiche import (
    MAX_PAGINE,
    _classifica,
)
from gestione_specifiche.models import EventoSpecifica, Specifica
from gestione_specifiche.share_link import risolvi_consentito


def _ascii(s: str) -> str:
    return (s or "").encode("ascii", "replace").decode("ascii")


class Command(BaseCommand):
    help = ("Importa come allegato raw nel portale il PDF della share per le specifiche importate "
            "PRISTINE (promuovibili), abilitando F6b-2 su di esse. Dry-run di default.")

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="esegue l'import (default: dry-run)")
        parser.add_argument("--limit", type=int, default=0, help="al piu' N specifiche (0 = tutte)")
        parser.add_argument("--pk", type=int, default=0, help="una sola specifica (pk)")
        parser.add_argument("--ocr", action="store_true",
                            help="classifica via OCR i PDF scansionati (richiede Tesseract; es. su pcgavancini)")

    def handle(self, *args, **opts):
        import fitz  # PyMuPDF

        qs = Specifica.objects.filter(percorso_esterno__gt="").order_by("pk")
        if opts["pk"]:
            qs = qs.filter(pk=opts["pk"])
        if opts["limit"]:
            qs = qs[:opts["limit"]]

        promossi = 0
        saltati = 0
        for spec in qs:
            if spec.allegato:  # ha gia' il raw nel portale
                continue
            motivo = self._promuovi(spec, fitz, apply=opts["apply"], ocr=opts["ocr"])
            if motivo == "ok":
                promossi += 1
            else:
                saltati += 1
                self.stdout.write(f"  SKIP [{motivo}]: {_ascii(spec.codice)} rev {_ascii(spec.revisione)}")

        modo = "APPLY" if opts["apply"] else "DRY-RUN"
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"[{modo}] promuovibili: {promossi} | saltati: {saltati}"))
        if not opts["apply"] and promossi:
            self.stdout.write("  (dry-run: nessuna scrittura. Rilancia con --apply per importare.)")

    # ------------------------------------------------------------------ helpers
    def _promuovi(self, spec, fitz, *, apply: bool, ocr: bool = False) -> str:
        """Ritorna 'ok' se (dry-run: promuoverebbe / apply: promosso), altrimenti il motivo di skip."""
        reale = risolvi_consentito(spec.percorso_esterno)
        if reale is None or not os.path.isfile(reale):
            return "irraggiungibile"
        try:
            doc = fitz.open(reale)
        except Exception as exc:  # noqa: BLE001
            return "non-apribile:" + _ascii(str(exc))[:40]
        try:
            if getattr(doc, "needs_pass", False):
                return "protetto-password"
            classe = _classifica(self._testo(doc, MAX_PAGINE))
            prima = _classifica(self._pagina(doc, 0))
            # OCR (scansioni): riclassifica documento e/o prima pagina se il testo non e' estraibile.
            if ocr and (classe == "incerto" or prima == "incerto"):
                if classe == "incerto":
                    t = self._ocr_testo(doc)
                    if t:
                        classe = _classifica(t)
                if prima == "incerto":
                    p = self._ocr_pagina(doc, 0)
                    if p:
                        prima = _classifica(p)
        finally:
            doc.close()
        if not (classe == "senza" and prima == "senza"):
            return f"non-pristino({classe}/{prima})"

        nome = os.path.basename(reale)
        self.stdout.write(f"  PROMUOVI: {_ascii(spec.codice)} rev {_ascii(spec.revisione)} <- {_ascii(nome)}")
        if apply:
            with open(reale, "rb") as fh:
                dati = fh.read()
            spec.allegato.save(nome, ContentFile(dati), save=False)  # scrive nello storage cifrato
            Specifica.objects.filter(pk=spec.pk).update(allegato=spec.allegato.name)  # persiste (no FSM)
            EventoSpecifica.objects.create(
                specifica=spec, stato_da=spec.stato, stato_a=spec.stato, attore=None,
                trigger="importa_raw_allegato",
                payload={"origine_share": spec.percorso_esterno,
                         "allegato": spec.allegato.name, "bytes": len(dati)},
            )
        return "ok"

    def _testo(self, doc, max_pagine: int) -> str:
        parti = []
        for i in range(min(doc.page_count, max_pagine)):
            try:
                parti.append(doc.load_page(i).get_text("text"))
            except Exception:  # noqa: BLE001
                continue
        return "\n".join(parti)

    def _pagina(self, doc, i: int) -> str:
        try:
            return doc.load_page(i).get_text("text")
        except Exception:  # noqa: BLE001
            return ""

    def _ocr_testo(self, doc, max_pagine: int = 3) -> str:
        """OCR delle prime pagine (richiede Tesseract). Guardato: '' se il motore manca."""
        parti = []
        try:
            for i in range(min(doc.page_count, max_pagine)):
                page = doc.load_page(i)
                tp = page.get_textpage_ocr(full=True)
                parti.append(page.get_text("text", textpage=tp))
            return "\n".join(parti)
        except Exception:  # noqa: BLE001
            return ""

    def _ocr_pagina(self, doc, i: int) -> str:
        try:
            page = doc.load_page(i)
            tp = page.get_textpage_ocr(full=True)
            return page.get_text("text", textpage=tp)
        except Exception:  # noqa: BLE001
            return ""
