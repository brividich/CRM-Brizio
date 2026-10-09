"""Riallineamento degli adempimenti quando cambiano le mansioni di rischio effettive.

Il piano di adeguamento nasce con lo spostamento (``cambio_mansione``). Ma le
mansioni di rischio effettive di una persona cambiano anche senza spostamento:

- **override individuale** aggiunto o revocato (addetto antincendio, preposto,
  esclusione indicata dal medico competente);
- **modifica admin** del collegamento mansione lavorativa ↔ mansione di rischio,
  o del contenuto di una mansione di rischio (fattori, visite, DPI): tocca tutti
  i dipendenti di quelle mansioni e gira in **background** con un report.

In tutti i casi si applica lo stesso *delta*: requisiti dopo − requisiti prima.
Ciò che si aggiunge e non è già soddisfatto diventa un adempimento sulla card
di assegnazione aperta; ciò che non è più dovuto chiude l'adempimento aperto
come «non più dovuto». Idempotente (chiave stabile + indice unique filtrato),
transazionale per persona, notifiche dopo il commit.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from . import eventi_sicurezza, mansionario, requisiti
from .cambio_mansione import chiave_voce, requisito_soddisfatto

logger = logging.getLogger(__name__)

# dominio del motore → tipo adempimento
_TIPO = {"visite": "VISITA", "corsi": "FORMAZIONE", "dpi": "DPI"}
_ETICHETTA = {"visite": "Visita", "corsi": "Corso", "dpi": "DPI"}


def _ids(req: dict, dominio: str) -> dict[int, object]:
    return {getattr(o, "pk", o): o for o in (req or {}).get(dominio) or []}


def _nome(obj) -> str:
    return getattr(obj, "nome", None) or getattr(obj, "titolo", None) or str(obj)


def card_aperta(legacy_id: int):
    """La card di assegnazione su cui ancorare gli adempimenti (aperta, la più recente)."""
    from ..models import DipendenteAssegnazione
    return (
        DipendenteAssegnazione.objects
        .filter(legacy_anagrafica_id=legacy_id, data_fine__isnull=True)
        .order_by("-data_inizio", "-created_at")
        .first()
    )


def applica_delta(
    legacy_id: int,
    prima: dict,
    dopo: dict,
    *,
    causa: str,
    entro_il: date | None = None,
    origine: dict | None = None,
    ancora_dovuti: dict | None = None,
    user=None,
    ctx=None,
    persona=None,
) -> dict[str, int]:
    """Applica il delta requisiti ``prima`` → ``dopo`` agli adempimenti della persona.

    ``ancora_dovuti``: requisiti completi attuali della persona; un requisito
    sparito dal delta ma ancora dovuto per un'altra fonte non viene chiuso.
    ``origine``: campi ``origine_*`` da registrare sugli adempimenti creati.
    """
    from ..models import AdempimentoCambioMansione as A, DipendenteAssegnazione

    esito = {"creati": 0, "non_piu_dovuti": 0, "gia_soddisfatti": 0, "senza_assegnazione": 0}
    card = card_aperta(legacy_id)
    if card is None:
        esito["senza_assegnazione"] = 1
        return esito
    entro = entro_il or max(timezone.localdate(), card.data_inizio)
    if ctx is None or persona is None:
        ctx = requisiti.ambito()
        persona = {d.id: d for d in ctx._tutti()}.get(ctx.canonico(legacy_id))

    with transaction.atomic():
        DipendenteAssegnazione.objects.select_for_update().filter(pk=card.pk).first()
        esistenti = {a.chiave: a for a in card.adempimenti.filter(attivo=True)}
        for dominio, tipo in _TIPO.items():
            prima_ids, dopo_ids = _ids(prima, dominio), _ids(dopo, dominio)
            for pk, obj in dopo_ids.items():
                if pk in prima_ids:
                    continue
                chiave = chiave_voce(tipo, pk)
                if chiave in esistenti:
                    continue
                if persona is not None and requisito_soddisfatto(
                    tipo, pk, ctx=ctx, persona=persona, dal=entro, mansione=card.mansione,
                ):
                    esito["gia_soddisfatti"] += 1
                    continue
                esistenti[chiave] = A.objects.create(
                    assegnazione=card, legacy_anagrafica_id=legacy_id, tipo=tipo, riferimento_id=pk,
                    chiave=chiave, descrizione=f"{_ETICHETTA[dominio]}: {_nome(obj)}"[:300],
                    motivo=causa[:300], entro_il=entro, **(origine or {"origine_tipo": "ALTRO"}),
                )
                esito["creati"] += 1
            dovuti = _ids(ancora_dovuti, dominio) if ancora_dovuti is not None else dopo_ids
            for pk in prima_ids:
                if pk in dopo_ids or pk in dovuti:
                    continue
                attuale = esistenti.get(chiave_voce(tipo, pk))
                if attuale is None or attuale.stato != A.STATO_APERTO:
                    continue
                attuale.stato = A.STATO_NON_PIU_DOVUTO
                attuale.attivo = False
                attuale.chiuso_il = timezone.now()
                attuale.chiuso_da = user if getattr(user, "is_authenticated", False) else None
                attuale.chiusura_nota = f"Non più dovuto: {causa}"[:300]
                attuale.save(update_fields=["stato", "attivo", "chiuso_il", "chiuso_da", "chiusura_nota"])
                esito["non_piu_dovuti"] += 1
        if esito["creati"] or esito["non_piu_dovuti"]:
            eventi_sicurezza.registra(
                legacy_id, "PIANO_AGGIORNATO",
                f"{causa}: {esito['creati']} adempimenti nuovi, {esito['non_piu_dovuti']} non più dovuti",
                user=user, oggetto=card,
                payload={"assegnazione_id": card.pk, "causa": causa[:200], **esito},
            )
    if esito["creati"]:
        transaction.on_commit(lambda: _notifica(legacy_id, card.pk))
    return esito


def _notifica(legacy_id: int, assegnazione_id: int) -> None:
    try:
        from .notifiche_cambio_mansione import notifica_piano_cambio_mansione
        notifica_piano_cambio_mansione(legacy_id, assegnazione_id)
    except Exception:
        logger.warning("notifica riallineamento fallita per %s", legacy_id, exc_info=True)


# ═══════════════════════════════════════════════════════════════════════════
# Override individuali
# ═══════════════════════════════════════════════════════════════════════════

def aggiungi_override(legacy_id: int, mansione_rischio, *, azione: str, motivo: str,
                      data_inizio: date, data_fine: date | None = None, user=None, request=None):
    """Crea un override (aggiunta/esclusione) e riallinea gli adempimenti."""
    from django.core.exceptions import ValidationError
    from ..models_mansioni_rischio import DipendenteMansioneRischioOverride as O

    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Il motivo è obbligatorio.")
    if azione not in (O.AZIONE_AGGIUNGI, O.AZIONE_ESCLUDI):
        raise ValidationError("Azione non valida.")
    if data_fine and data_fine < data_inizio:
        raise ValidationError("La data di fine precede quella di inizio.")
    giorno = max(timezone.localdate(), data_inizio)
    with transaction.atomic():
        if O.objects.select_for_update().filter(
            legacy_anagrafica_id=legacy_id, mansione_rischio=mansione_rischio, attivo=True,
        ).exists():
            raise ValidationError("Esiste già un override attivo per questa mansione di rischio: revocalo prima.")
        prima = mansionario.requisiti_dipendente(legacy_id, data=giorno)
        override = O.objects.create(
            legacy_anagrafica_id=legacy_id, mansione_rischio=mansione_rischio, azione=azione,
            motivo=motivo[:500], data_inizio=data_inizio, data_fine=data_fine,
            created_by=user if getattr(user, "is_authenticated", False) else None,
        )
        dopo = mansionario.requisiti_dipendente(legacy_id, data=giorno)
        eventi_sicurezza.registra(
            legacy_id, "OVERRIDE_AGGIUNTO",
            f"{override.get_azione_display()}: «{mansione_rischio.nome}» dal {data_inizio:%d/%m/%Y}",
            user=user, request=request, data_effetto=data_inizio, oggetto=override,
            payload={"override_id": override.pk, "mansione_rischio_id": mansione_rischio.pk,
                     "azione": azione, "motivo": motivo[:300]},
        )
        esito = applica_delta(
            legacy_id, prima, dopo, causa=f"{override.get_azione_display()} «{mansione_rischio.nome}»",
            entro_il=giorno, user=user,
            origine={"origine_tipo": "OVERRIDE", "origine_mansione_rischio_id": mansione_rischio.pk,
                     "origine_override_id": override.pk},
        )
    return override, esito


def revoca_override(override, *, motivo: str, user=None, request=None):
    """Revoca (non cancella) un override e riallinea gli adempimenti."""
    from django.core.exceptions import ValidationError

    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError("Il motivo della revoca è obbligatorio.")
    if not override.attivo:
        return override, {}
    legacy_id = override.legacy_anagrafica_id
    giorno = timezone.localdate()
    with transaction.atomic():
        prima = mansionario.requisiti_dipendente(legacy_id, data=giorno)
        override.attivo = False
        override.revocato_il = timezone.now()
        override.revocato_da = user if getattr(user, "is_authenticated", False) else None
        override.revoca_motivo = motivo[:300]
        override.save(update_fields=["attivo", "revocato_il", "revocato_da", "revoca_motivo"])
        dopo = mansionario.requisiti_dipendente(legacy_id, data=giorno)
        eventi_sicurezza.registra(
            legacy_id, "OVERRIDE_REVOCATO",
            f"Revocato: {override.get_azione_display().lower()} «{override.mansione_rischio.nome}»",
            user=user, request=request, oggetto=override,
            payload={"override_id": override.pk, "motivo": motivo[:300]},
        )
        esito = applica_delta(
            legacy_id, prima, dopo,
            causa=f"Revoca {override.get_azione_display().lower()} «{override.mansione_rischio.nome}»",
            user=user, origine={"origine_tipo": "MANSIONE"},
        )
    return override, esito


# ═══════════════════════════════════════════════════════════════════════════
# Modifica admin (molti dipendenti): job in background
# ═══════════════════════════════════════════════════════════════════════════

def _serializza(req: dict) -> dict[str, list[int]]:
    return {d: sorted(_ids(req, d)) for d in _TIPO}


def dipendenti_della_mansione(mansione_ids: Iterable[int]) -> list[int]:
    """Dipendenti attivi la cui mansione (per nome) è fra quelle indicate."""
    from ..models import Mansione
    nomi = {n.strip().casefold() for n in Mansione.objects.filter(pk__in=list(mansione_ids)).values_list("nome", flat=True)}
    if not nomi:
        return []
    from core.legacy_anagrafica import fetch_anagrafica_rows
    return sorted(
        int(r["id"]) for r in fetch_anagrafica_rows(deduplicate=True)
        if str(r.get("mansione") or "").strip().casefold() in nomi and r.get("attivo", True)
    )


def fotografa_mansioni(mansione_ids: Iterable[int]) -> dict[int, dict[str, list[int]]]:
    """Requisiti di livello mansione, da prendere PRIMA di una modifica admin."""
    return {int(m): _serializza(mansionario.requisiti_mansione(int(m))) for m in mansione_ids}


def accoda_riallineamento(prima: dict[int, dict[str, list[int]]], *, causa: str, user_id: int | None = None) -> None:
    """Accoda (dopo il commit) il riallineamento dei dipendenti delle mansioni fotografate."""
    payload = {str(k): v for k, v in prima.items()}

    def _enqueue():
        try:
            from django_q.tasks import async_task
            async_task("anagrafica.services.riallineamento.esegui_riallineamento", payload, causa, user_id,
                       q_options={"timeout": 600})
        except Exception:
            logger.warning("riallineamento non accodato: eseguo in linea", exc_info=True)
            esegui_riallineamento(payload, causa, user_id)

    transaction.on_commit(_enqueue)


def esegui_riallineamento(prima: dict, causa: str, user_id: int | None = None) -> dict:
    """Corpo del job: per ogni mansione toccata, delta prima/dopo su ogni dipendente.

    Ritorna (e scrive in audit) il report: dipendenti, adempimenti creati,
    non più dovuti, già soddisfatti, senza assegnazione, errori.
    """
    from django.contrib.auth import get_user_model
    from ..models import Mansione

    user = get_user_model().objects.filter(pk=user_id).first() if user_id else None
    report = {"causa": causa, "mansioni": 0, "dipendenti": 0, "creati": 0, "non_piu_dovuti": 0,
              "gia_soddisfatti": 0, "senza_assegnazione": 0, "errori": 0}
    ctx = requisiti.ambito()
    tutti = {d.id: d for d in ctx._tutti()}
    for mansione_id, req_prima in prima.items():
        mansione = Mansione.objects.filter(pk=int(mansione_id)).first()
        if mansione is None:
            continue
        report["mansioni"] += 1
        # La fotografia contiene solo id: ``_ids`` accetta interi così come sono.
        req_dopo = mansionario.requisiti_mansione(mansione)
        for legacy_id in dipendenti_della_mansione([mansione.pk]):
            report["dipendenti"] += 1
            try:
                attuali = mansionario.requisiti_dipendente(legacy_id, mansione_nome=mansione.nome)
                esito = applica_delta(
                    legacy_id, req_prima, req_dopo, causa=f"{causa} (mansione «{mansione.nome}»)",
                    ancora_dovuti=attuali, user=user, ctx=ctx, persona=tutti.get(ctx.canonico(legacy_id)),
                    origine={"origine_tipo": "MANSIONE_RISCHIO"},
                )
            except Exception:
                logger.exception("riallineamento fallito per %s", legacy_id)
                report["errori"] += 1
                continue
            for k in ("creati", "non_piu_dovuti", "gia_soddisfatti", "senza_assegnazione"):
                report[k] += esito.get(k, 0)
    try:
        from core.audit import log_action
        log_action(None, "riallineamento_mansioni_rischio", "anagrafica", report,
                   oggetto_tipo="anagrafica.mansionerischio", oggetto_id="job")
    except Exception:
        logger.warning("report riallineamento non scritto in audit", exc_info=True)
    return report
