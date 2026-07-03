"""#2 tool — «Applica timbri»: il compilatore posiziona i timbri sul composito (drag&drop).

Le specifiche non sono tutte uguali: invece di posizioni fisse, chi compila trascina i timbri
dove vuole sulle pagine (rese come immagini). Le posizioni (in punti PDF) si salvano su
``TimbroApplicazione`` e vengono applicate al composito alla generazione (fallback: automatico).
"""
from __future__ import annotations

import base64
import json
import math

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from .models import Specifica, TimbroApplicazione, TimbroCapocommessa


def _leggi_file(field) -> bytes | None:
    if not field:
        return None
    try:
        with field.open("rb") as fh:
            return fh.read()
    except Exception:  # noqa: BLE001
        return None


def _thumb_uri(raw: bytes, name: str) -> str:
    name = (name or "").lower()
    if name.endswith(".pdf"):
        import fitz
        d = fitz.open(stream=raw, filetype="pdf")
        raw = d[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=True).tobytes("png")
        d.close()
        mime = "image/png"
    elif name.endswith((".jpg", ".jpeg")):
        mime = "image/jpeg"
    else:
        mime = "image/png"
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


def _n_mod133(spec) -> int:
    try:
        return max(1, math.ceil(spec.mod133.righe.count() / 7))
    except Exception:  # noqa: BLE001
        return 1


@login_required
def applica_timbri(request, pk: int):
    spec = get_object_or_404(Specifica, pk=pk)
    n_mod133 = _n_mod133(spec)

    if request.method == "POST":
        try:
            payload = json.loads(request.body or "{}")
        except Exception:  # noqa: BLE001
            return JsonResponse({"ok": False, "error": "payload non valido"}, status=400)
        spec.timbri_applicati.all().delete()
        n = 0
        for pl in payload.get("placements", []):
            t = TimbroCapocommessa.objects.filter(pk=pl.get("timbro"), attivo=True).first()
            if not t:
                continue
            page = int(pl.get("page", 0))
            sez = TimbroApplicazione.SEZ_MOD133 if page < n_mod133 else TimbroApplicazione.SEZ_ORIGINALE
            pag = page if page < n_mod133 else page - n_mod133
            TimbroApplicazione.objects.create(
                specifica=spec, timbro=t, sezione=sez, pagina=pag,
                x=float(pl.get("x", 0)), y=float(pl.get("y", 0)), w=float(pl.get("w", 120)))
            n += 1
        return JsonResponse({"ok": True, "n": n})

    # GET — anteprima del composito (senza timbri, senza protezione) resa in pagine PNG
    from .composito import _leggi_pdf_originale, componi_composito_ufficiale, dati_mod133_da_spec

    pagine, errore = [], ""
    originale = _leggi_pdf_originale(spec)
    if not originale:
        errore = "PDF originale non disponibile: collega o carica l'allegato prima di applicare i timbri."
    else:
        try:
            import fitz
            composite = componi_composito_ufficiale(originale, dati_mod133_da_spec(spec), proteggi=False)
            doc = fitz.open(stream=composite, filetype="pdf")
            for i, page in enumerate(doc):
                pix = page.get_pixmap(matrix=fitz.Matrix(1.4, 1.4))
                pagine.append({
                    "idx": i, "sezione": "MOD.133" if i < n_mod133 else "Originale",
                    "ptw": round(page.rect.width, 1), "pth": round(page.rect.height, 1),
                    "uri": "data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode(),
                })
            doc.close()
        except Exception as exc:  # noqa: BLE001
            errore = f"Impossibile generare l'anteprima: {exc}"

    palette = []
    for t in TimbroCapocommessa.objects.filter(attivo=True).order_by("tipo", "codice"):
        raw = _leggi_file(t.file)
        if not raw:
            continue
        palette.append({
            "id": t.pk, "codice": t.codice, "tipo": t.get_tipo_display(),
            "is_ricevuto": t.tipo == TimbroCapocommessa.TIPO_RICEVUTO,
            "uri": _thumb_uri(raw, t.file.name),
        })

    esistenti = []
    for a in spec.timbri_applicati.select_related("timbro").all():
        page = a.pagina if a.sezione == TimbroApplicazione.SEZ_MOD133 else n_mod133 + a.pagina
        esistenti.append({"timbro": a.timbro_id, "page": page, "x": a.x, "y": a.y, "w": a.w})

    return render(request, "gestione_specifiche/applica_timbri.html", {
        "spec": spec, "pagine": pagine, "palette": palette, "errore": errore,
        "esistenti_json": json.dumps(esistenti), "n_mod133": n_mod133,
    })
