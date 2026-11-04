"""«Importa planimetrie»: dai PDF dei servizi alle piante pronte da validare.

Per ogni PDF: la pagina diventa l'immagine di una pianta nuova (o aggiorna quella
nata dallo stesso file), la pianta diventa un livello della pianta base allineato
da solo sui muri (``planimetria_allinea``) e le categorie vengono dalla legenda.
Gli asset non si collocano qui: la lettura del PDF salvato si apre da «Valida
asset» e le posizioni si scrivono solo per le righe confermate.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone

from ..models import PlantLayout
from . import planimetria_allinea as allinea_mod
from . import planimetria_livelli as livelli
from . import planimetria_pagina as pagina_pdf

SOGLIA_SICURO = 0.70  # sotto: allineamento salvato ma «da verificare»
_DATA = re.compile(r"[\s_-]+(?:\d{1,2}[._-])?\d{1,2}[._-]\d{2,4}\s*$")  # « 02_2026», « 04_11_2024»


class ErroreImportazione(ValueError):
    pass


def nome_servizio(nome_file: str, legenda=None) -> str:
    """«PLANIMETRIA CONDIZIONATORI E CALDAIE 02_2026.pdf» → «Condizionatori e caldaie»."""
    servizio = (getattr(legenda, "servizio", "") or "").strip()
    if not servizio:
        servizio = Path(nome_file or "").stem
        servizio = re.sub(r"^\s*planimetria\s*", "", servizio, flags=re.IGNORECASE)
        servizio = _DATA.sub("", servizio)
        servizio = servizio.replace("_", " ").strip(" -_.")
    servizio = re.sub(r"\s+", " ", servizio).strip()
    if not servizio:
        return "Planimetria"
    return servizio[:1].upper() + servizio[1:].lower()


def importa_pdf(contenuto: bytes, nome_file: str, base: PlantLayout, utente: str = "") -> dict:
    """Crea (o aggiorna) la pianta del PDF come livello di ``base``; restituisce l'esito per la pagina."""
    from PIL import Image

    from . import planimetria_lettura as lettura_mod
    from .planimetria_lettura import categorie_ammesse, pagina_pdf_png

    lettura_mod._CACHE_CATEGORIE.clear()  # categorie create nel frattempo

    if base is None or not base.image:
        raise ErroreImportazione("Scegli una pianta base con l'immagine.")
    try:
        pag = pagina_pdf.leggi_pdf(contenuto, 0, ocr_se_vuoto=False)
        png = pagina_pdf_png(contenuto, 0)
    except Exception as exc:  # PDF rotto o cifrato
        raise ErroreImportazione(f"«{nome_file}» non si legge come PDF: {exc}") from exc

    servizio = nome_servizio(nome_file, pag.legenda)
    layout = (
        PlantLayout.objects.filter(importazione__file=nome_file).order_by("-id").first()
        if nome_file else None
    )
    nuova = layout is None
    if nuova:
        attiva_altrove = PlantLayout.objects.filter(is_active=True, category__iexact=servizio).exists()
        layout = PlantLayout(category=servizio, name=f"Planimetria {servizio.lower()}"[:120],
                             is_active=not attiva_altrove)
    stem = re.sub(r"[^A-Za-z0-9]+", "-", Path(nome_file).stem).strip("-")[:60] or "planimetria"
    layout.image.save(f"{stem}.png", ContentFile(png), save=False)
    if layout.sorgente_pdf:
        layout.sorgente_pdf.delete(save=False)
    layout.sorgente_pdf.save(f"{stem}.pdf", ContentFile(contenuto), save=False)
    layout.base = base
    layout.importazione = {
        "file": nome_file, "il": timezone.now().isoformat(timespec="minutes"), "da": utente,
        "validata": False,
    }
    layout.save()

    # categorie dalla legenda (o dal titolo «PLANIMETRIA CARROPONTI»)
    categorie_nomi: list[str] = []
    if not layout.asset_categories.exists():
        from ..models import AssetCategory

        ids, perche = categorie_ammesse(PlantLayout(), pag.legenda)
        if ids and perche:
            radici = list(AssetCategory.objects.filter(id__in=ids).exclude(parent_id__in=ids))
        else:
            # niente dalla legenda: il nome del servizio («Carroponti» → Carroponte); una pianta di
            # servizio mostra tutta la famiglia (gru e paranchi stanno sulla pianta dei carroponti)
            radici = []
            for c in lettura_mod.categorie_per_testo(servizio):
                radice = c
                for _ in range(4):
                    if not radice.parent_id:
                        break
                    radice = AssetCategory.objects.filter(pk=radice.parent_id).first() or radice
                    if radice.pk == c.pk:
                        break
                if radice not in radici:
                    radici.append(radice)
        if radici:
            layout.asset_categories.set(radici)
    categorie_nomi = list(layout.asset_categories.values_list("label", flat=True))

    # allineamento sui muri della pianta base
    esito = None
    try:
        with Image.open(base.image.path) as img_base, Image.open(io.BytesIO(png)) as img_liv:
            img_base.load()
            img_liv.load()
            esito = allinea_mod.allinea(img_liv, img_base, pag.riquadri)
    except (OSError, ValueError):
        esito = None
    allineato = False
    if esito is not None and esito.buono:
        livelli.salva_allineamento(layout, base, esito.punti)
        layout.allineamento = {**layout.allineamento, "automatico": True, "punteggio": esito.punteggio,
                               "da_verificare": esito.punteggio < SOGLIA_SICURO}
        allineato = True
    else:
        layout.allineamento = {}
        if not layout.colore:
            usati = set(PlantLayout.objects.filter(base=base).exclude(pk=layout.pk).values_list("colore", flat=True))
            layout.colore = next((c for c in livelli.COLORI_LIVELLI if c not in usati), livelli.COLORI_LIVELLI[0])
    layout.importazione = {**layout.importazione, "punteggio": esito.punteggio if esito else None}
    layout.save(update_fields=["allineamento", "colore", "importazione", "updated_at"])
    return riga(layout, nuova=nuova, allineato=allineato, categorie=categorie_nomi)


def riga(layout: PlantLayout, *, nuova: bool | None = None, allineato: bool | None = None,
         categorie: list[str] | None = None) -> dict:
    """Una riga della tabella «Piante importate»."""
    from django.urls import reverse

    editor = reverse("assets:plant_layout_editor")
    imp = layout.importazione or {}
    al = layout.allineamento or {}
    if allineato is None:
        allineato = bool(layout.matrice)
    if categorie is None:
        categorie = list(layout.asset_categories.values_list("label", flat=True))
    if not allineato:
        stato_al, livello_al = "Da allineare a mano", "rosso"
    elif al.get("da_verificare"):
        stato_al, livello_al = "Allineata, da controllare", "giallo"
    else:
        stato_al, livello_al = "Allineata", "verde"
    return {
        "id": layout.id,
        "nome": layout.name,
        "categoria": layout.category,
        "file": imp.get("file", ""),
        "attiva": layout.is_active,
        "nuova": nuova,
        "categorie": categorie,
        "allineamento": stato_al,
        "allineamento_livello": livello_al,
        "punteggio": imp.get("punteggio"),
        "validata": bool(imp.get("validata")),
        "validata_il": imp.get("validata_il", ""),
        "asset": layout.markers.count(),
        "url_valida": f"{editor}?leggi=1&layout={layout.id}&sorgente=1",
        "url_allineamento": f"{editor}?livello={layout.id}",
        "url_editor": f"{editor}?layout={layout.id}",
    }


def segna_validata(layout: PlantLayout, utente: str = "") -> None:
    if not layout.importazione:
        return
    layout.importazione = {**layout.importazione, "validata": True,
                           "validata_il": timezone.now().isoformat(timespec="minutes"), "validata_da": utente}
    layout.save(update_fields=["importazione", "updated_at"])
