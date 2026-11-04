"""«Leggi planimetria»: proposte di posizione degli asset dai testi della pianta.

Pagina servita dalla rotta dell'editor (``?leggi=1``), quindi con lo stesso
permesso «Editor mappa officina». Legge (PDF vettoriale o OCR dell'immagine,
eventualmente AI locale), mostra le proposte e scrive i marker solo per le
righe confermate. Se il PDF diventa l'immagine della pianta nasce una **nuova
versione** non attiva, con reparti e macchine copiati: la pianta attuale non si tocca.

Dalla stessa lettura si possono anche **creare gli asset** che sulla pianta ci
sono ma in anagrafica no (sigla, categoria, descrizione e costruttore dalla
legenda) e **disegnare i reparti** scritti sulla pianta.
"""
from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.contrib import messages
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from ..models import Asset, AssetCategory, PlantLayout, PlantLayoutArea, PlantLayoutMarker
from ..services import planimetria_lettura as lettura

_CARTELLA_TEMP = "planimetrie_lettura"
_TOKEN = re.compile(r"^[0-9a-f]{32}$")
_MAX_PDF = 60 * 1024 * 1024


def _url_editor(layout: PlantLayout) -> str:
    return f"{reverse('assets:plant_layout_editor')}?layout={layout.id}&category={quote(layout.category)}"


def _ocr_disponibile() -> bool:
    try:
        from anagrafica.services.referti_ocr import percorso_tesseract
        return bool(percorso_tesseract())
    except Exception:
        return False


def _ai_disponibile() -> bool:
    try:
        from ai_assistant.services import chat_with_ollama  # noqa: F401
        return True
    except Exception:
        return False


def _pulisci_anteprime() -> None:
    """Le pagine PDF lette e mai applicate restano un giorno, poi si cancellano."""
    from datetime import timedelta

    from django.utils import timezone

    try:
        _cartelle, files = default_storage.listdir(_CARTELLA_TEMP)
    except (FileNotFoundError, NotImplementedError, OSError):
        return
    limite = timezone.now() - timedelta(days=1)
    for nome in files:
        percorso = f"{_CARTELLA_TEMP}/{nome}"
        try:
            if default_storage.get_modified_time(percorso) < limite:
                default_storage.delete(percorso)
        except (OSError, NotImplementedError):
            continue


def _layout_da_richiesta(request) -> PlantLayout | None:
    try:
        layout_id = int(request.POST.get("layout_id") or request.GET.get("layout") or 0)
    except (TypeError, ValueError):
        return None
    return PlantLayout.objects.filter(pk=layout_id).first() if layout_id else None


def leggi_planimetria(request: HttpRequest) -> HttpResponse:
    layouts = list(PlantLayout.objects.order_by("category", "-is_active", "name"))
    layout = _layout_da_richiesta(request) or next((x for x in layouts if x.is_active), None)
    contesto = {
        "layouts": layouts,
        "layout": layout,
        "ocr_disponibile": _ocr_disponibile(),
        "ai_disponibile": _ai_disponibile(),
        "risultato": None,
    }
    if request.method != "POST" or layout is None:
        return render(request, "assets/pages/planimetria_lettura.html", contesto)

    action = (request.POST.get("action") or "").strip()
    if action == "applica_proposte":
        return _applica(request, layout)

    file_pdf = request.FILES.get("pdf")
    usa_ai = request.POST.get("usa_ai") == "1"
    token = ""
    try:
        if file_pdf:
            if file_pdf.size > _MAX_PDF:
                raise lettura.ErroreLettura("Il PDF è troppo grande (massimo 60 MB).")
            contenuto = file_pdf.read()
            try:
                pagina = max(0, int(request.POST.get("pagina") or 1) - 1)
            except ValueError:
                pagina = 0
            pag = lettura.leggi_pagina_pdf(contenuto, pagina)
            fonte = f"{'Riconoscimento del testo sul' if pag.ocr else 'Testo del'} PDF «{file_pdf.name}», pagina {pagina + 1}"
            if not pag.parole and not any(sim.testo for sim in pag.simboli):
                raise lettura.ErroreLettura(
                    "Sul PDF non si legge nessuna scritta: stampalo su PDF dal disegno, oppure togli il PDF e "
                    "usa la lettura dell'immagine."
                )
            if request.POST.get("usa_pdf_immagine") == "1":
                _pulisci_anteprime()
                token = uuid.uuid4().hex
                default_storage.save(f"{_CARTELLA_TEMP}/{token}.png", ContentFile(lettura.pagina_pdf_png(contenuto, pagina)))
        else:
            if not layout.image:
                raise lettura.ErroreLettura("La planimetria non ha un'immagine da leggere.")
            pag = lettura.leggi_pagina_immagine(layout.image.path)
            fonte = "Riconoscimento del testo sull'immagine della planimetria"
    except lettura.ErroreLettura as exc:
        messages.error(request, str(exc))
        return render(request, "assets/pages/planimetria_lettura.html", contesto)

    risultato = lettura.abbina(layout, usa_ai=usa_ai, fonte_testo=fonte, pagina=pag)
    if file_pdf and not token:
        risultato.avvisi.append(
            "Le posizioni sono calcolate sulla pagina del PDF: combaciano solo se l'immagine della planimetria è la "
            "stessa pagina intera. Altrimenti spunta «Usa questa pagina come immagine della planimetria»."
        )
    contesto.update({
        "risultato": risultato,
        "token_immagine": token,
        "anteprima_url": default_storage.url(f"{_CARTELLA_TEMP}/{token}.png") if token else (
            layout.image.url if layout.image else ""
        ),
        "usa_ai": usa_ai,
        "categorie": list(AssetCategory.objects.filter(is_active=True).only("id", "label").order_by("label")),
        "tipi_legenda": [{"colore": c, "testo": t} for c, t in (risultato.legenda.tipi if risultato.legenda else [])],
    })
    return render(request, "assets/pages/planimetria_lettura.html", contesto)


def _coordinata(valore) -> Decimal | None:
    try:
        d = Decimal(str(valore)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if 0 <= d <= 100 else None


def _applica(request: HttpRequest, layout: PlantLayout) -> HttpResponse:
    from .layout import _record_plant_position_changes

    nuovi = _righe_da_creare(request)
    reparti = _righe_reparti(request)
    scelte = []
    for voce in request.POST.getlist("sel"):
        try:
            asset_id, x, y = voce.split(":")
            asset_id = int(asset_id)
        except ValueError:
            continue
        x, y = _coordinata(x), _coordinata(y)
        if x is not None and y is not None:
            scelte.append((asset_id, x, y))
    if not scelte and not nuovi and not reparti:
        messages.warning(request, "Nessuna proposta selezionata: niente è cambiato.")
        return redirect(f"{reverse('assets:plant_layout_editor')}?leggi=1&layout={layout.id}")

    destinazione = layout
    token = (request.POST.get("token_immagine") or "").strip()
    if token and _TOKEN.match(token) and default_storage.exists(f"{_CARTELLA_TEMP}/{token}.png"):
        from ..services.plant_layout_image import copy_layout_content

        percorso = f"{_CARTELLA_TEMP}/{token}.png"
        destinazione = PlantLayout(category=layout.category, name=f"{layout.name} (da PDF)"[:120],
                                   description=layout.description, is_active=False)
        with default_storage.open(percorso, "rb") as f:
            destinazione.image.save(f"{token}.png", ContentFile(f.read()), save=False)
        destinazione.save()
        copy_layout_content(layout, destinazione)
        default_storage.delete(percorso)

    validi = set(Asset.objects.filter(pk__in=[s[0] for s in scelte]).values_list("pk", flat=True))
    cambi = []
    for asset_id, x, y in scelte:
        if asset_id not in validi:
            continue
        marker, creato = PlantLayoutMarker.objects.get_or_create(
            layout=destinazione, asset_id=asset_id, defaults={"x_percent": x, "y_percent": y, "is_visible": True},
        )
        if not creato:
            if marker.x_percent == x and marker.y_percent == y and marker.is_visible:
                continue
            marker.x_percent, marker.y_percent, marker.is_visible = x, y, True
            marker.save(update_fields=["x_percent", "y_percent", "is_visible", "updated_at"])
        cambi.append((asset_id, "collocata" if creato else "spostata"))
    creati = _crea_asset(request, destinazione, nuovi)
    cambi += [(a.id, "collocata") for a in creati]
    _record_plant_position_changes(request, destinazione, cambi)
    disegnati = _crea_reparti(destinazione, reparti)
    extra = []
    if creati:
        extra.append(f"creati {len(creati)} asset nuovi")
    if disegnati:
        extra.append(f"disegnati {disegnati} reparti")
    coda = (" (" + ", ".join(extra) + ")") if extra else ""
    if destinazione is layout:
        messages.success(request, f"Collocati o spostati {len(cambi)} asset sulla planimetria «{layout.name}»{coda}.")
    else:
        messages.success(
            request,
            f"Creata la nuova versione «{destinazione.name}» (non ancora attiva) con {len(cambi)} asset dalla lettura{coda}: "
            "controllala e usa «Pubblica come attiva».",
        )
    return redirect(_url_editor(destinazione))


def _righe_da_creare(request: HttpRequest) -> list[dict]:
    """Righe «Crea asset» spuntate: sigla, nome, categoria, posizione, descrizione e costruttore dalla legenda."""
    righe = []
    for indice in request.POST.getlist("crea"):
        if not str(indice).isdigit():
            continue
        dato = lambda k: (request.POST.get(f"crea_{k}_{indice}") or "").strip()  # noqa: E731
        sigla, nome = dato("sigla")[:60], dato("nome")[:255]
        x, y = _coordinata(dato("x")), _coordinata(dato("y"))
        categoria = AssetCategory.objects.filter(pk=dato("categoria"), is_active=True).first() if dato("categoria").isdigit() else None
        if not sigla or not nome or x is None or y is None or categoria is None:
            continue
        righe.append({"sigla": sigla, "nome": nome, "categoria": categoria, "x": x, "y": y,
                      "descrizione": dato("descrizione")[:255], "costruttore": dato("costruttore")[:120]})
    return righe[:500]


def _numero_interno(sigla: str) -> str:
    # come gli altri asset in anagrafica: «Int.C5», «Int.233»
    return sigla if sigla.lower().startswith("int") else f"Int.{sigla}"


def _crea_asset(request: HttpRequest, layout: PlantLayout, righe: list[dict]) -> list[Asset]:
    # la collocazione finisce nella timeline con le altre (_record_plant_position_changes)
    creati = []
    for r in righe:
        numero = _numero_interno(r["sigla"])
        # niente doppioni: una sigla che nel frattempo esiste già non si ricrea
        if Asset.objects.filter(internal_number__iexact=numero).exclude(status=Asset.STATUS_RETIRED).exists():
            continue
        asset = Asset(
            name=r["nome"], internal_number=numero, asset_category=r["categoria"],
            asset_type=r["categoria"].base_asset_type or Asset.TYPE_OTHER,
            manufacturer=r["costruttore"] or None, assignment_location=r["descrizione"][:200],
            notes=f"Creato da «Leggi planimetria» sulla pianta «{layout.name}».",
        )
        asset.save()
        PlantLayoutMarker.objects.get_or_create(
            layout=layout, asset=asset, defaults={"x_percent": r["x"], "y_percent": r["y"], "is_visible": True},
        )
        creati.append(asset)
    return creati


def _righe_reparti(request: HttpRequest) -> list[dict]:
    righe = []
    for indice in request.POST.getlist("reparto"):
        if not str(indice).isdigit():
            continue
        dato = lambda k: (request.POST.get(f"rep_{k}_{indice}") or "").strip()  # noqa: E731
        nome = dato("nome")[:120]
        valori = [_coordinata(dato(k)) for k in ("x", "y", "w", "h")]
        if not nome or any(v is None for v in valori) or valori[2] < Decimal("0.5") or valori[3] < Decimal("0.5"):
            continue
        righe.append({"nome": nome, "x": valori[0], "y": valori[1], "w": valori[2], "h": valori[3]})
    return righe[:100]


_COLORI_REPARTI = ["#2563EB", "#16A34A", "#D97706", "#9333EA", "#DC2626", "#0891B2", "#65A30D", "#DB2777"]


def _crea_reparti(layout: PlantLayout, righe: list[dict]) -> int:
    esistenti = {n.casefold() for n in layout.areas.values_list("name", flat=True)}
    fatti = 0
    for i, r in enumerate(righe):
        if r["nome"].casefold() in esistenti:
            continue
        PlantLayoutArea.objects.create(
            layout=layout, name=r["nome"], reparto_code=r["nome"], color=_COLORI_REPARTI[i % len(_COLORI_REPARTI)],
            x_percent=r["x"], y_percent=r["y"], width_percent=min(r["w"], Decimal("100") - r["x"]),
            height_percent=min(r["h"], Decimal("100") - r["y"]),
        )
        esistenti.add(r["nome"].casefold())
        fatti += 1
    return fatti
