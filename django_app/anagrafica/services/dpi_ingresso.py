"""Servizi per la consegna DPI all'ingresso del dipendente.

Il flusso (dal form di creazione dipendente):
1. HR sceglie i ruoli operativi del nuovo dipendente.
2. Il portale propone le categorie DPI ``obbligatoria_mansionario=True``.
3. HR conferma quali consegnare (checkbox + modello/taglia/quantità).
4. Al salvataggio, ``crea_consegne_iniziali`` registra in atomic:
   - una ``RichiestaDPI`` per ogni riga, già APPROVATA + CONSEGNATA
   - la relativa ``ConsegnaDPI`` (firma differita)
5. ``archivia_pdf_cumulativo`` genera un unico PDF con tutte le consegne
   iniziali e lo archivia in ``DocumentoDipendente``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Sequence

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from dpi.models import (
    CategoriaDPI,
    ConsegnaDPI,
    ModelloDPI,
    RichiestaDPI,
    StatoRichiesta,
    TagliaDPI,
    TipoDPI,
)


logger = logging.getLogger(__name__)
User = get_user_model()


@dataclass
class RigaConsegnaIniziale:
    """Una riga di consegna iniziale proposta/confermata da HR."""
    categoria_id: int
    quantita: int = 1
    tipo_id: int | None = None
    modello_id: int | None = None
    taglia_id: int | None = None


def categorie_obbligatorie_per_ruoli(ruoli_ids: Iterable[int]) -> list[CategoriaDPI]:
    """Categorie DPI obbligatorie da mansionario per i ruoli operativi indicati.

    Fase 1: tutte le ``CategoriaDPI.obbligatoria_mansionario=True`` attive.
    L'eventuale filtro per ruolo (M2M dedicato su CategoriaDPI) è una
    estensione futura: il dato oggi non esiste a schema.
    """
    # Argomento ``ruoli_ids`` accettato per compatibilità futura; non filtra
    # ancora per non introdurre dipendenze di schema non richieste in questa fase.
    _ = list(ruoli_ids or [])
    return list(
        CategoriaDPI.objects
        .filter(is_active=True, obbligatoria_mansionario=True)
        .order_by("order_index", "nome")
    )


def proposta_righe_iniziali(ruoli_ids: Iterable[int]) -> list[dict]:
    """Costruisce la lista di righe da pre-compilare nel form HTMX.

    Una riga per categoria obbligatoria, con modello/taglia non preimpostati
    (HR sceglierà dal dropdown in base a quanto disponibile a magazzino).
    """
    out = []
    for cat in categorie_obbligatorie_per_ruoli(ruoli_ids):
        out.append({
            "categoria": cat,
            "categoria_id": cat.id,
            "modelli": list(
                ModelloDPI.objects.filter(
                    is_active=True, tipo__categoria_id=cat.id
                ).select_related("tipo")
            ),
        })
    return out


def _build_richiedente_fields(civile, aziendale) -> dict:
    """Estrae i campi denormalizzati del richiedente da civile + aziendale."""
    full_name_parts = []
    legacy_id = civile.legacy_anagrafica_id if civile else None
    # Il nome/cognome NON sta sulla nostra anagrafica civile: viene dal sistema
    # legacy. Per la consegna iniziale ci basta legacy_id; nome è facoltativo.
    nome_display = f"Dipendente #{legacy_id}" if legacy_id else "Nuovo dipendente"
    email = ""
    if aziendale:
        email = aziendale.email_aziendale or ""
        reparto = aziendale.area or ""
    else:
        reparto = ""
    if not email and civile:
        email = civile.email_privata or ""
    return {
        "richiedente_legacy_id": legacy_id,
        "richiedente_nome": nome_display,
        "richiedente_email": email,
        "richiedente_reparto": reparto,
    }


def _calcola_scadenza_stimata(modello: ModelloDPI | None, categoria: CategoriaDPI, data_consegna: date) -> date | None:
    vita_utile = None
    if modello is not None:
        vita_utile = modello.effective_vita_utile_giorni
    if vita_utile is None:
        vita_utile = categoria.vita_utile_giorni
    if vita_utile:
        return data_consegna + timedelta(days=vita_utile)
    return None


@transaction.atomic
def crea_consegne_iniziali(
    civile,
    aziendale,
    righe: Sequence[RigaConsegnaIniziale],
    user,
    data_consegna: date | None = None,
) -> list[ConsegnaDPI]:
    """Crea ``RichiestaDPI`` (APPROVATA→CONSEGNATA) + ``ConsegnaDPI`` per ogni riga.

    Tutte le operazioni avvengono in atomic; un singolo errore fa rollback
    di tutte le consegne iniziali (il dipendente resta comunque creato:
    la transaction atomica del chiamante decide cosa farne).
    """
    if not righe:
        return []
    if data_consegna is None:
        data_consegna = timezone.localdate()

    richiedente_fields = _build_richiedente_fields(civile, aziendale)
    consegnato_da = ""
    if user is not None and getattr(user, "is_authenticated", False):
        consegnato_da = user.get_full_name() or user.username

    consegne: list[ConsegnaDPI] = []
    for riga in righe:
        try:
            categoria = CategoriaDPI.objects.get(pk=riga.categoria_id, is_active=True)
        except CategoriaDPI.DoesNotExist:
            logger.warning("Categoria DPI %s non trovata: skip riga", riga.categoria_id)
            continue

        tipo = None
        modello = None
        taglia = None
        if riga.tipo_id:
            tipo = TipoDPI.objects.filter(pk=riga.tipo_id, is_active=True).first()
        if riga.modello_id:
            modello = ModelloDPI.objects.filter(pk=riga.modello_id, is_active=True).first()
        if riga.taglia_id:
            taglia = TagliaDPI.objects.filter(pk=riga.taglia_id, is_active=True).first()

        richiesta = RichiestaDPI.objects.create(
            categoria=categoria,
            tipo_dpi=tipo,
            modello_dpi=modello,
            taglia_dpi=taglia,
            quantita=max(1, int(riga.quantita or 1)),
            motivazione="Consegna iniziale all'ingresso",
            stato=StatoRichiesta.APPROVATA,
            created_by=user if user and user.is_authenticated else None,
            **richiedente_fields,
        )
        scadenza = _calcola_scadenza_stimata(modello, categoria, data_consegna)
        consegna = ConsegnaDPI.objects.create(
            richiesta=richiesta,
            data_consegna=data_consegna,
            consegnato_da_nome=consegnato_da,
            firmato_ricevuta=False,
            data_scadenza_stimata=scadenza,
            firma_immagine="",
        )
        # Promuovi la richiesta a CONSEGNATA dopo aver creato la consegna
        richiesta.stato = StatoRichiesta.CONSEGNATA
        richiesta.save(update_fields=["stato", "updated_at"])
        consegne.append(consegna)
    return consegne


def archivia_pdf_cumulativo(consegne: Sequence[ConsegnaDPI], user, descrizione: str = "") -> "object | None":
    """Genera un PDF unico per le consegne iniziali e lo archivia.

    Ritorna il ``DocumentoDipendente`` creato o ``None`` in caso di errore.
    Fail-soft: gli errori sono loggati ma non sollevano.
    """
    if not consegne:
        return None
    try:
        from dpi.pdf import render_modulo_consegna_dpi_multipla

        from ..models import DocumentoDipendente
    except Exception:
        logger.exception("Import dipendenze archivio PDF cumulativo fallito")
        return None

    legacy_id = consegne[0].richiesta.richiedente_legacy_id
    if not legacy_id:
        logger.warning("archivia_pdf_cumulativo: nessun legacy_id, salto archivio")
        return None

    try:
        pdf_bytes = render_modulo_consegna_dpi_multipla(consegne)
    except Exception:
        logger.exception("Errore generazione PDF consegne iniziali")
        return None

    today = timezone.localdate()
    nome_file = f"consegna_dpi_ingresso_{legacy_id}_{today:%Y%m%d}.pdf"
    descrizione = descrizione or "Consegna iniziale DPI all'ingresso"

    try:
        doc = DocumentoDipendente(
            legacy_anagrafica_id=legacy_id,
            tipo=DocumentoDipendente.Tipo.DPI_CONSEGNA,
            nome_originale=nome_file,
            tipo_mime="application/pdf",
            dimensione_bytes=len(pdf_bytes),
            descrizione=descrizione,
            oggetto_riferimento_tipo="dpi.consegna_ingresso",
            oggetto_riferimento_id=consegne[0].pk,
            created_by=user if user and user.is_authenticated else None,
            created_by_display=(
                user.get_full_name() or user.username
            ) if user and user.is_authenticated else "",
        )
        doc.file.save(nome_file, ContentFile(pdf_bytes), save=True)
        return doc
    except Exception:
        logger.exception("Errore archivio PDF cumulativo consegne iniziali")
        return None
