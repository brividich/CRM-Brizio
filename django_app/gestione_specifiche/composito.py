"""F6a — Orchestrazione OFFLINE del composito ufficiale MOD.133 (nessuna scrittura sulla share).

Al milestone (MOD.133 approvato) il file ufficiale = **[pagina MOD.133 compilata] + [PDF
originale]**, protetto (owner-password no-stampa/no-modifica, filigrana opzionale). Qui si
mettono insieme i mattoni gia' pronti:

    F4 ``mod133_render.render_mod133``  (pagina PDF del MOD.133 dai dati del portale)
    F3 ``pdf_compose.anteponi_pagine``  (antepone la pagina all'originale)
    F3 ``pdf_compose.applica_protezione`` (cifra + permessi + filigrana)

Tutto in memoria: si LEGGE l'originale (allegato locale cifrato oppure PDF sulla share via
``share_link.risolvi_consentito``, allowlist) e si RITORNANO i byte del composito. La scrittura
sulla share (deposito) e' un passo separato (F2 ``share_write``) da eseguire/rivedere a parte.

Scoping F6a: la pagina MOD.133 viene **anteposta** all'originale. La sostituzione di una cover
"in attesa" (rilevata da F1) e l'aggancio alla transizione FSM restano a F6b.
"""
from __future__ import annotations

import logging
import os

from django.conf import settings

from .mod133_overlay import render_mod133_overlay
from .mod133_render import render_cover_attesa
from .pdf_compose import anteponi_pagine, applica_filigrana, applica_protezione

logger = logging.getLogger(__name__)


def _nome_utente(u) -> str:
    if u is None:
        return ""
    nome = ""
    try:
        nome = (u.get_full_name() or "").strip()
    except Exception:  # noqa: BLE001
        nome = ""
    return nome or getattr(u, "username", "") or ""


def _owner_password_default() -> str:
    return str((getattr(settings, "GESTIONE_SPECIFICHE", {}) or {}).get("PDF_OWNER_PASSWORD", "") or "")


def dati_mod133_da_spec(spec) -> dict:
    """Costruisce il dict ``dati`` per ``render_mod133`` dai modelli MOD133/RigaMOD133 del portale.

    Mappa (F4): rif_paragrafo->paragrafi, argomento->argomenti, impatto_documenti->impatto_doc(SI/NO),
    descrizione_impatto->impatto_doc_desc, impatto_operativo->impatto_operativo(SI/NO),
    rif_paragrafo_cn->paragrafi_cn, descrizione_modifiche->argomenti_cn; compilatore->revisore,
    approvatore->approvatore. Chiavi mancanti -> celle vuote (il renderer non solleva).
    """
    try:
        mod = spec.mod133  # OneToOne
    except Exception:  # noqa: BLE001 - RelatedObjectDoesNotExist
        mod = None

    righe_qs = list(mod.righe.all()) if mod is not None else []
    righe = [{
        "paragrafi": r.rif_paragrafo,
        "argomenti": r.argomento,
        "impatto_doc": "SI" if r.impatto_documenti else "NO",
        "impatto_doc_desc": r.descrizione_impatto,
        "impatto_operativo": "SI" if r.impatto_operativo else "NO",
        "paragrafi_cn": r.rif_paragrafo_cn,
        "argomenti_cn": r.descrizione_modifiche,
    } for r in righe_qs]

    docs_cn = sorted({r.rif_doc_cn for r in righe_qs if r.rif_doc_cn})
    data = ""
    if mod is not None:
        d = mod.data_approvazione or mod.data_chiusura_compilazione
        if d:
            try:
                data = d.strftime("%d/%m/%Y")
            except Exception:  # noqa: BLE001
                data = ""

    doc_analizzato = f"{spec.codice} Rev.{spec.revisione}".strip()
    if spec.titolo:
        doc_analizzato = f"{doc_analizzato} - {spec.titolo}"

    return {
        "fonte": spec.cliente or "",
        "documento_analizzato": doc_analizzato,
        "documenti_cn_interessati": "; ".join(docs_cn),
        "data": data,
        "righe": righe,
        "note": spec.note or "",
        "revisore": _nome_utente(getattr(mod, "compilatore", None)) if mod is not None else "",
        "approvatore": _nome_utente(getattr(mod, "approvatore", None)) if mod is not None else "",
    }


def _risolvi_timbri(spec) -> dict | None:
    """#2 — Timbri per il composito: RICEVUTO del compilatore + firme MOD.133 di compilatore e
    approvatore. Ritorna il dict per ``applica_timbri`` (o None se nessun timbro configurato)."""
    try:
        mod = spec.mod133
    except Exception:  # noqa: BLE001
        return None

    from django.utils import timezone

    from .models import TimbroCapocommessa

    def _leggi(utente, tipo):
        if not utente:
            return None
        t = (TimbroCapocommessa.objects
             .filter(utente=utente, tipo=tipo, attivo=True)
             .order_by("-creato_il").first())
        if not t or not t.file:
            return None
        try:
            with t.file.open("rb") as fh:
                return fh.read()
        except Exception as exc:  # noqa: BLE001
            logger.debug("composito: timbro non leggibile: %s", exc)
            return None

    comp = getattr(mod, "compilatore", None)
    appr = getattr(mod, "approvatore", None)
    ricevuto = _leggi(comp, TimbroCapocommessa.TIPO_RICEVUTO)
    rev = _leggi(comp, TimbroCapocommessa.TIPO_MOD133)
    app = _leggi(appr, TimbroCapocommessa.TIPO_MOD133)
    if not any([ricevuto, rev, app]):
        return None
    return {
        "ricevuto": ricevuto,
        "stamp_revisore": rev,
        "stamp_approvatore": app,
        "data_testo": timezone.now().strftime("%d/%m/%Y"),
    }


def _leggi_pdf_originale(spec) -> bytes | None:
    """Byte del PDF originale della specifica (READ-ONLY): allegato locale cifrato o share.

    Il PDF sulla share si legge SOLO se dentro l'allowlist (``share_link.risolvi_consentito``).
    """
    alleg = getattr(spec, "allegato", None)
    if alleg:
        try:
            with alleg.open("rb") as fh:
                dati = fh.read()
            if dati:
                return dati
        except Exception as exc:  # noqa: BLE001
            logger.debug("composito: allegato non leggibile: %s", exc)

    perc = (getattr(spec, "percorso_esterno", "") or "").strip()
    if perc:
        from .share_link import risolvi_consentito

        reale = risolvi_consentito(perc)
        if reale and os.path.isfile(reale):
            try:
                with open(reale, "rb") as fh:
                    return fh.read()
            except OSError as exc:
                logger.debug("composito: PDF share non leggibile: %s", exc)
    return None


def componi_composito_ufficiale(
    originale_pdf: bytes,
    dati_mod133: dict,
    *,
    owner_password: str = "",
    proteggi: bool = True,
    consenti_stampa: bool = False,
    consenti_modifica: bool = False,
    consenti_copia: bool = False,
    filigrana: str | None = None,
    timbri: dict | None = None,
) -> bytes:
    """[pagina MOD.133] + [originale], opzionalmente protetto. Ritorna i byte del composito.

    Non tocca l'originale su disco: lavora su copie in memoria. Con ``proteggi=True`` applica
    la cifratura owner-password (default: nega stampa e modifica) e l'eventuale filigrana.
    """
    if not originale_pdf:
        raise ValueError("PDF originale mancante: impossibile comporre il composito.")
    # M11: un composito "protetto" con owner-password vuota sarebbe sbloccabile da chiunque
    # (protezione nulla). Fail-closed: non lo produciamo.
    if proteggi and not owner_password:
        raise ValueError(
            "Owner-password mancante: impossibile produrre un composito protetto "
            "(configurare GESTIONE_SPECIFICHE_PDF_OWNER_PASSWORD nel .env)."
        )
    # #1: usa il MOD.133 REALE come template (overlay pymupdf), non il render reportlab.
    pagina_mod133 = render_mod133_overlay(dati_mod133)
    composito = anteponi_pagine(originale_pdf, [pagina_mod133])
    # #2: timbri (RICEVUTO sul documento originale + firme sul MOD.133) PRIMA della protezione.
    if timbri:
        import math

        from .timbri_overlay import applica_timbri
        n_mod133 = max(1, math.ceil(len(dati_mod133.get("righe") or []) / 7))
        composito = applica_timbri(composito, n_pagine_mod133=n_mod133, **timbri)
    if proteggi:
        composito = applica_protezione(
            composito,
            owner_password=owner_password,
            consenti_stampa=consenti_stampa,
            consenti_modifica=consenti_modifica,
            consenti_copia=consenti_copia,
            filigrana=filigrana,
        )
    return composito


def componi_composito_da_spec(
    spec,
    *,
    originale: bytes | None = None,
    owner_password: str | None = None,
    proteggi: bool = True,
    consenti_stampa: bool = False,
    consenti_modifica: bool = False,
    consenti_copia: bool = False,
    filigrana: str | None = None,
) -> bytes:
    """Composito ufficiale a partire dalla Specifica (dati MOD.133 dal DB, originale READ-ONLY).

    ``originale`` puo' essere fornito (es. il PDF appena caricato dal DM); altrimenti si legge
    quello collegato alla specifica. ``owner_password`` di default viene dai settings
    (``GESTIONE_SPECIFICHE['PDF_OWNER_PASSWORD']``, segreto da .env). Solleva ``ValueError`` se
    l'originale non e' disponibile. NON scrive nulla sulla share.
    """
    pdf = originale if originale is not None else _leggi_pdf_originale(spec)
    if not pdf:
        raise ValueError("PDF originale della specifica non disponibile (ne allegato ne share leggibili).")
    pw = owner_password if owner_password is not None else _owner_password_default()
    return componi_composito_ufficiale(
        pdf,
        dati_mod133_da_spec(spec),
        owner_password=pw,
        proteggi=proteggi,
        consenti_stampa=consenti_stampa,
        consenti_modifica=consenti_modifica,
        consenti_copia=consenti_copia,
        filigrana=filigrana,
        timbri=_risolvi_timbri(spec),  # #2: timbri RICEVUTO + firme MOD.133
    )


# Filigrana della forma "in attesa" (non ancora compilato/approvato il MOD.133).
FILIGRANA_ATTESA = "SOLO PER CONSULTAZIONE"


def _dati_cover_attesa(spec) -> dict:
    data = ""
    d = getattr(spec, "data_inserimento", None)
    if d:
        try:
            data = d.strftime("%d/%m/%Y")
        except Exception:  # noqa: BLE001
            data = ""
    return {
        "codice": spec.codice,
        "revisione": spec.revisione,
        "titolo": spec.titolo,
        "cliente": spec.cliente or "",
        "data": data,
    }


def componi_attesa_da_spec(
    spec,
    *,
    originale: bytes | None = None,
    owner_password: str | None = None,
    proteggi: bool = True,
    filigrana: str = FILIGRANA_ATTESA,
) -> bytes:
    """Forma "IN ATTESA MOD.133": [cover attesa] + [originale] + filigrana (+ protezione).

    Usata prima della compilazione/approvazione del MOD.133 (F6b, deposito sulla share). Con
    ``proteggi=True`` cifra owner-password e applica la filigrana in un colpo solo; con
    ``proteggi=False`` (anteprima) applica solo la filigrana VISIBILE senza cifrare. Non scrive
    nulla sulla share. Solleva ``ValueError`` se l'originale non e' disponibile o (protetto) senza
    owner-password.
    """
    pdf = originale if originale is not None else _leggi_pdf_originale(spec)
    if not pdf:
        raise ValueError("PDF originale della specifica non disponibile (ne allegato ne share leggibili).")
    cover = render_cover_attesa(_dati_cover_attesa(spec))
    composito = anteponi_pagine(pdf, [cover])
    if proteggi:
        pw = owner_password if owner_password is not None else _owner_password_default()
        if not pw:
            raise ValueError(
                "Owner-password mancante: impossibile produrre la forma protetta "
                "(configurare GESTIONE_SPECIFICHE_PDF_OWNER_PASSWORD nel .env)."
            )
        composito = applica_protezione(
            composito, owner_password=pw,
            consenti_stampa=False, consenti_modifica=False, consenti_copia=False,
            filigrana=filigrana,
        )
    elif filigrana:
        composito = applica_filigrana(composito, filigrana)
    return composito
