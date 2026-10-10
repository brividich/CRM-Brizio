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
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from .models import EventoSpecifica, Specifica, TimbroApplicazione, TimbroCapocommessa


def timbri_ammessi(spec, user=None):
    """Timbri che possono comparire sul composito di ``spec``.

    Sono solo quelli delle persone del MOD.133: tutti i timbri attivi del **compilatore**
    (RICEVUTO e firma MOD.133) e la sola firma MOD.133 dell'**approvatore**. L'approvatore
    viene registrato sul MOD.133 all'approvazione, quindi la sua firma non è disponibile
    prima. Se il MOD.133 non ha ancora un compilatore, vale l'utente che sta lavorando
    (``user``); senza nessuno dei due il risultato è vuoto. È lo stesso filtro usato in
    composizione, così una posizione salvata non stampa mai il timbro di un estraneo.
    """
    try:
        mod = spec.mod133
    except Exception:  # noqa: BLE001
        mod = None
    compilatore_id = getattr(mod, "compilatore_id", None) or (
        getattr(user, "pk", None) if getattr(user, "is_authenticated", False) else None
    )
    approvatore_id = getattr(mod, "approvatore_id", None)
    cond = Q(pk__in=[])
    if compilatore_id:
        cond |= Q(utente_id=compilatore_id)
    if approvatore_id:
        cond |= Q(utente_id=approvatore_id, tipo=TimbroCapocommessa.TIPO_MOD133)
    return TimbroCapocommessa.objects.filter(cond, attivo=True)


def _placement_valido(pl) -> dict | None:
    """Valida una posizione dal client: numeri finiti, pagina >= 0, larghezza plausibile."""
    if not isinstance(pl, dict):
        return None
    try:
        timbro = int(pl.get("timbro"))
        page = int(pl.get("page", 0))
        x, y, w = float(pl.get("x", 0)), float(pl.get("y", 0)), float(pl.get("w", 120))
    except (TypeError, ValueError):
        return None
    if page < 0 or not all(math.isfinite(v) for v in (x, y, w)) or not (4 <= w <= 2000):
        return None
    return {"timbro": timbro, "page": page, "x": x, "y": y, "w": w}


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
        raw = payload.get("placements", []) if isinstance(payload, dict) else None
        if not isinstance(raw, list):
            return JsonResponse({"ok": False, "error": "payload non valido"}, status=400)
        placements = [_placement_valido(pl) for pl in raw]
        if any(p is None for p in placements):
            return JsonResponse({"ok": False, "error": "posizione non valida"}, status=400)

        ammessi = {t.pk: t for t in timbri_ammessi(spec, request.user)}
        scartati = sorted({p["timbro"] for p in placements if p["timbro"] not in ammessi})
        if scartati:
            # Niente salvataggio parziale: chi prova ad apporre un timbro non suo lo sa subito.
            return JsonResponse(
                {"ok": False, "error": "Puoi apporre solo i timbri del compilatore e, a MOD.133 "
                                       "approvato, la firma dell'approvatore."},
                status=403,
            )

        registro = []
        with transaction.atomic():
            spec.timbri_applicati.all().delete()
            for p in placements:
                t = ammessi[p["timbro"]]
                page = p["page"]
                sez = TimbroApplicazione.SEZ_MOD133 if page < n_mod133 else TimbroApplicazione.SEZ_ORIGINALE
                pag = page if page < n_mod133 else page - n_mod133
                TimbroApplicazione.objects.create(
                    specifica=spec, timbro=t, sezione=sez, pagina=pag, x=p["x"], y=p["y"], w=p["w"])
                registro.append({"timbro": t.pk, "codice": t.codice, "tipo": t.tipo,
                                 "titolare": t.utente_id, "sezione": sez, "pagina": pag})
            # Traccia di chi ha posizionato quali timbri e quando (EventoSpecifica è append-only).
            EventoSpecifica.objects.create(
                specifica=spec, stato_da=spec.stato, stato_a=spec.stato,
                attore=request.user if request.user.is_authenticated else None,
                trigger="timbri_applicati", payload={"n": len(registro), "timbri": registro},
            )
        return JsonResponse({"ok": True, "n": len(registro)})

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
    # Solo i timbri applicabili a questa specifica: le firme degli altri non lasciano il server.
    for t in timbri_ammessi(spec, request.user).order_by("tipo", "codice"):
        raw = _leggi_file(t.file)
        if not raw:
            continue
        palette.append({
            "id": t.pk, "codice": t.codice, "tipo": t.get_tipo_display(),
            "is_ricevuto": t.tipo == TimbroCapocommessa.TIPO_RICEVUTO,
            "uri": _thumb_uri(raw, t.file.name),
        })

    esistenti = []
    ammessi_ids = {p["id"] for p in palette}
    for a in spec.timbri_applicati.select_related("timbro").all():
        if a.timbro_id not in ammessi_ids:
            continue
        page = a.pagina if a.sezione == TimbroApplicazione.SEZ_MOD133 else n_mod133 + a.pagina
        esistenti.append({"timbro": a.timbro_id, "page": page, "x": a.x, "y": a.y, "w": a.w})

    return render(request, "gestione_specifiche/applica_timbri.html", {
        "spec": spec, "pagine": pagine, "palette": palette, "errore": errore,
        "esistenti_json": json.dumps(esistenti), "n_mod133": n_mod133,
    })
