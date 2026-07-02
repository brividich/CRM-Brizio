"""Detector/inventario dei PDF collegati alle Specifiche (READ-ONLY, MOD.133 F1).

Scandisce le `Specifica` che hanno un PDF (percorso sulla share UNC in
`percorso_esterno`, con precedenza, oppure `allegato` locale cifrato) e classifica
ciascun PDF in base al contenuto testuale delle prime pagine:

- ``mod133``       = contiene una pagina del modulo MOD.133 (Tabella di verifica
                     dei nuovi requisiti / Flow Down);
- ``cover_attesa`` = contiene la cover "SPECIFICA IN ATTESA DI COMPILAZIONE MOD.133";
- ``senza``        = testo presente ma nessuno dei due marker;
- ``incerto``      = nessun testo estraibile (probabile scansione immagine);
- ``irraggiungibile`` = il PDF non e' apribile (percorso fuori allowlist, file
                     mancante sulla share, allegato illeggibile).

La risoluzione del percorso sulla share passa SEMPRE per
`share_link.risolvi_consentito` (allowlist + anti-traversal): i path fuori radice
sono classificati ``irraggiungibile``, mai aperti. Il comando NON scrive nulla su
DB ne' sulla share: produce solo un report CSV (--out) e un riepilogo a console.

Per i PDF ``incerto`` (scansioni) e' previsto un fallback OCR LEGGERO opzionale
(--ocr), guardato da import/try-except: se il motore OCR non e' disponibile il PDF
resta ``incerto`` con una nota, senza mai far fallire il comando.

Esempi::

    python manage.py analizza_pdf_specifiche --out "C:/report/inventario_pdf.csv"
    python manage.py analizza_pdf_specifiche --out "C:/report/inventario_pdf.csv" --limit 50
    python manage.py analizza_pdf_specifiche --out "C:/report/inventario_pdf.csv" --ocr
"""
from __future__ import annotations

import os
import re
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from gestione_specifiche.models import Specifica
from gestione_specifiche.share_link import radici_consentite, risolvi_consentito

# Numero massimo di pagine di cui estrarre il testo per la classificazione.
MAX_PAGINE = 12
# Numero massimo di pagine su cui tentare l'OCR (fallback leggero).
OCR_MAX_PAGINE = 3

# Marker forti del modulo MOD.133 (whitespace collassato, confronto case-insensitive).
MOD133_MARKERS = (
    "TABELLA DI VERIFICA DEI NUOVI REQUISITI",
    "FLOW DOWN FOR NEW REQUIREMENTS",
    "Mod.133 - FLD - Flow Down Requisiti - Rev.2",
)
# Marker della cover "in attesa di compilazione".
COVER_MARKERS = (
    "SPECIFICA IN ATTESA DI COMPILAZIONE",
)


def _ascii(s: str) -> str:
    """Rende una stringa sicura per la console cp1252 (solo ASCII)."""
    return (s or "").encode("ascii", "replace").decode("ascii")


def _normalizza(testo: str) -> str:
    """Collassa ogni sequenza di spazi/newline in un singolo spazio."""
    return re.sub(r"\s+", " ", (testo or "")).strip()


def _classifica(testo: str) -> str:
    """Classifica il testo estratto. MOD.133 ha precedenza sulla cover."""
    norm = _normalizza(testo)
    if not norm:
        return "incerto"
    up = norm.upper()
    for m in MOD133_MARKERS:
        if m.upper() in up:
            return "mod133"
    for m in COVER_MARKERS:
        if m.upper() in up:
            return "cover_attesa"
    return "senza"


class Command(BaseCommand):
    help = (
        "Inventario READ-ONLY dei PDF delle Specifiche: classifica in mod133 / "
        "cover_attesa / senza / incerto / irraggiungibile e scrive un report CSV."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--out", default="",
            help="Percorso del report CSV (pk;codice;revisione;classe;prima_pagina;promuovibile;pagine;path;note).",
        )
        parser.add_argument(
            "--limit", type=int, default=0,
            help="Analizza al piu' N specifiche (0 = tutte).",
        )
        parser.add_argument(
            "--ocr", action="store_true",
            help="Abilita il fallback OCR leggero sui PDF 'incerto' (richiede motore OCR; se assente resta 'incerto').",
        )

    def handle(self, *args, **opts):
        try:
            import fitz  # noqa: F401  (PyMuPDF)
        except ImportError as exc:
            raise CommandError("PyMuPDF (fitz) non disponibile: " + _ascii(str(exc)))

        out = (opts.get("out") or "").strip()
        radici = radici_consentite()

        cond = Q(percorso_esterno__gt="") | Q(allegato__gt="")
        qs = Specifica.objects.filter(cond).order_by("pk")
        if opts["limit"]:
            qs = qs[:opts["limit"]]

        cnt = Counter()
        n_promuovibili = 0
        righe = []
        problemi = []
        for spec in qs:
            classe, prima, pagine, path_str, nota = self._analizza(spec, fitz, ocr=opts["ocr"])
            cnt[classe] += 1
            # RAW pristino = nessun marker MOD.133/cover nel doc E prima pagina = contenuto:
            # candidato a essere "promosso" come allegato raw nel portale per F6b-2.
            promuovibile = (classe == "senza" and prima == "senza")
            if promuovibile:
                n_promuovibili += 1
            righe.append({
                "pk": spec.pk,
                "codice": spec.codice,
                "revisione": spec.revisione,
                "classe": classe,
                "prima_pagina": prima,
                "promuovibile": "si" if promuovibile else "",
                "pagine": pagine,
                "path": path_str,
                "note": nota,
            })
            if classe in ("irraggiungibile", "incerto") and len(problemi) < 40:
                problemi.append(
                    f"  {classe}: {_ascii(spec.codice)} rev {_ascii(spec.revisione)}"
                    f" -> {_ascii(path_str)} ({_ascii(nota)})"
                )

        if out:
            self._scrivi_csv(out, righe)

        self.stdout.write(self.style.MIGRATE_HEADING("Analisi PDF specifiche (READ-ONLY)"))
        if not radici:
            self.stdout.write(self.style.NOTICE(
                "  GESTIONE_SPECIFICHE_SHARE_ROOTS non configurata: i percorsi su share risultano 'irraggiungibile'."
            ))
        self.stdout.write(f"  radici consentite: {[_ascii(r) for r in radici]}")
        self.stdout.write(f"  analizzate: {sum(cnt.values())} | {dict(cnt)}")
        self.stdout.write(
            f"  raw pristini 'promuovibili' (senza + prima pagina = contenuto): {n_promuovibili}"
        )
        for p in problemi:
            self.stdout.write(self.style.WARNING(p))
        if out:
            self.stdout.write(f"  report CSV: {_ascii(out)}")
        else:
            self.stdout.write(self.style.NOTICE("  (nessun --out: report CSV non scritto)"))

    # ----------------------------------------------------------------- helpers

    def _scrivi_csv(self, out: str, righe: list) -> None:
        import csv

        cartella = os.path.dirname(out)
        if cartella:
            os.makedirs(cartella, exist_ok=True)
        campi = ["pk", "codice", "revisione", "classe", "prima_pagina", "promuovibile",
                 "pagine", "path", "note"]
        with open(out, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=campi, delimiter=";")
            writer.writeheader()
            writer.writerows(righe)

    def _analizza(self, spec, fitz, ocr: bool = False):
        """Ritorna (classe, prima_pagina, pagine, path_str, nota). Non solleva mai: gli errori
        di apertura diventano classe 'irraggiungibile'.

        - ``classe`` = classificazione del documento (marker nelle prime/ultime pagine);
        - ``prima_pagina`` = classificazione della SOLA pagina 1 (cover_attesa/mod133/senza/incerto):
          serve a distinguere un raw PRISTINO (prima pagina = contenuto = 'senza') da un file
          gia' compositato (prima pagina = cover_attesa/mod133).
        """
        percorso = (getattr(spec, "percorso_esterno", "") or "").strip()
        path_str = ""
        doc = None
        try:
            if percorso:
                path_str = percorso
                reale = risolvi_consentito(percorso)
                if reale is None:
                    return ("irraggiungibile", "", 0, path_str, "path non consentito (fuori allowlist)")
                if not os.path.isfile(reale):
                    return ("irraggiungibile", "", 0, path_str, "file non trovato sulla share")
                doc = fitz.open(reale)
            else:
                allegato = getattr(spec, "allegato", None)
                if not allegato:
                    return ("irraggiungibile", "", 0, "", "nessun percorso_esterno ne allegato")
                path_str = allegato.name
                try:
                    with allegato.open("rb") as fh:
                        dati = fh.read()
                    doc = fitz.open(stream=dati, filetype="pdf")
                except Exception as exc:  # noqa: BLE001  (report, mai crash)
                    return ("irraggiungibile", "", 0, path_str, "allegato non leggibile: " + _ascii(str(exc)))
        except Exception as exc:  # noqa: BLE001
            return ("irraggiungibile", "", 0, path_str, "apertura fallita: " + _ascii(str(exc)))

        try:
            pagine = doc.page_count
            if getattr(doc, "needs_pass", False):
                # PDF con user-password: il contenuto non e' leggibile (diverso da una scansione).
                return ("incerto", "incerto", pagine, path_str,
                        "pdf protetto da password utente (contenuto non leggibile)")
            testo = self._estrai_testo(doc, MAX_PAGINE)
            classe = _classifica(testo)
            prima = _classifica(self._testo_pagina(doc, 0))
            nota = ""
            if classe == "incerto" or prima == "incerto":
                if ocr:
                    testo_ocr, nota_ocr = self._ocr_testo(doc, fitz)
                    if classe == "incerto" and testo_ocr:
                        classe = _classifica(testo_ocr)
                    p0_ocr = self._ocr_pagina(doc, 0)
                    if p0_ocr:
                        prima = _classifica(p0_ocr)
                    nota = "ocr: " + nota_ocr
                else:
                    nota = "nessun testo estraibile (probabile scansione); usa --ocr"
            return (classe, prima, pagine, path_str, nota)
        finally:
            try:
                doc.close()
            except Exception:  # noqa: BLE001
                pass

    def _testo_pagina(self, doc, i: int) -> str:
        try:
            return doc.load_page(i).get_text("text")
        except Exception:  # noqa: BLE001
            return ""

    def _ocr_pagina(self, doc, i: int) -> str:
        """OCR della sola pagina ``i`` (per la prima pagina). Guardato: '' se il motore manca."""
        try:
            page = doc.load_page(i)
            tp = page.get_textpage_ocr(full=True)
            return _normalizza(page.get_text("text", textpage=tp))
        except Exception:  # noqa: BLE001
            return ""

    def _estrai_testo(self, doc, max_pagine: int) -> str:
        parti = []
        n = doc.page_count
        indici = list(range(min(n, max_pagine)))
        # Coda: se il PDF e' piu' lungo del cap, controlla anche le ultime 2 pagine
        # (una pagina MOD.133 puo' essere accodata in fondo a uno storico voluminoso).
        if n > max_pagine:
            for i in (n - 2, n - 1):
                if i >= 0 and i not in indici:
                    indici.append(i)
        for i in indici:
            try:
                parti.append(doc.load_page(i).get_text("text"))
            except Exception:  # noqa: BLE001
                continue
        return "\n".join(parti)

    def _ocr_testo(self, doc, fitz):
        """Fallback OCR leggero via PyMuPDF (richiede Tesseract). Guardato: se il
        motore non c'e' ritorna ('', motivo) senza sollevare."""
        parti = []
        try:
            n = min(doc.page_count, OCR_MAX_PAGINE)
            for i in range(n):
                page = doc.load_page(i)
                tp = page.get_textpage_ocr(full=True)
                parti.append(page.get_text("text", textpage=tp))
            testo = _normalizza("\n".join(parti))
            if not testo:
                return ("", "nessun testo dall'OCR")
            return (testo, "eseguito")
        except Exception as exc:  # noqa: BLE001
            return ("", "motore OCR non disponibile: " + _ascii(str(exc)))
