"""«Leggi planimetria»: proposte di posizione degli asset dai testi della pianta.

Pagina servita dalla rotta dell'editor (``?leggi=1``), quindi con lo stesso
permesso «Editor mappa officina». Legge (PDF vettoriale o OCR dell'immagine,
eventualmente AI locale), mostra le proposte e scrive i marker solo per le
righe confermate. Se il PDF diventa l'immagine della pianta nasce una **nuova
versione** non attiva, con reparti e macchine copiati: la pianta attuale non si tocca.
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

from ..models import Asset, PlantLayout, PlantLayoutMarker
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
            parole, _dim = lettura.parole_da_pdf(contenuto, pagina)
            fonte = f"Testo del PDF «{file_pdf.name}», pagina {pagina + 1}"
            if not parole:
                raise lettura.ErroreLettura(
                    "Il PDF non contiene testo (è una scansione): stampalo su PDF dal disegno, oppure togli il PDF e "
                    "usa la lettura dell'immagine."
                )
            if request.POST.get("usa_pdf_immagine") == "1":
                _pulisci_anteprime()
                token = uuid.uuid4().hex
                default_storage.save(f"{_CARTELLA_TEMP}/{token}.png", ContentFile(lettura.pagina_pdf_png(contenuto, pagina)))
        else:
            if not layout.image:
                raise lettura.ErroreLettura("La planimetria non ha un'immagine da leggere.")
            parole = lettura.parole_da_immagine(layout.image.path)
            fonte = "Riconoscimento del testo sull'immagine della planimetria"
    except lettura.ErroreLettura as exc:
        messages.error(request, str(exc))
        return render(request, "assets/pages/planimetria_lettura.html", contesto)

    risultato = lettura.abbina(layout, parole, usa_ai=usa_ai, fonte_testo=fonte)
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
    if not scelte:
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
    _record_plant_position_changes(request, destinazione, cambi)
    if destinazione is layout:
        messages.success(request, f"Collocati o spostati {len(cambi)} asset sulla planimetria «{layout.name}».")
    else:
        messages.success(
            request,
            f"Creata la nuova versione «{destinazione.name}» (non ancora attiva) con {len(cambi)} asset dalla lettura: "
            "controllala e usa «Pubblica come attiva».",
        )
    return redirect(_url_editor(destinazione))
