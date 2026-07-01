"""F7 — API django-ninja per gestione_specifiche.

Endpoint di sola lettura (elenco/ricerca, dettaglio, eventi) + transizioni di
stato. Autenticazione di sessione; CSRF attivo per i metodi non sicuri (POST).
API/AJAX restituiscono JSON 401/403 (no redirect HTML).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django_fsm import TransitionNotAllowed
from django.core.exceptions import ValidationError
from ninja import NinjaAPI, Schema
from ninja.security import django_auth

from . import constants as C
from .models import Specifica

# `django_auth` (SessionAuth): autenticazione di sessione del HUB; in django-ninja
# 1.x abilita automaticamente la protezione CSRF sui metodi non sicuri (POST).
api = NinjaAPI(
    title="Gestione Specifiche API",
    version="1.0.0",
    urls_namespace="gestione_specifiche_api",
    auth=django_auth,
)


# Transizioni esponibili via API (whitelist).
_TRANSIZIONI_API = {
    "avvia_flow_down", "approva_flow_down", "respingi_flow_down",
    "sospendi", "ripristina", "annulla", "marca_duplicato",
    "errore_tecnico", "ripristina_da_errore",
}


class SpecificaOut(Schema):
    id: int
    codice: str
    revisione: str
    titolo: str
    tipo: str
    fonte: str
    cliente: str
    tag: str
    stato: str
    stato_display: Optional[str] = None
    data_inserimento: datetime
    data_verifica: Optional[date] = None
    mod133_esito: Optional[str] = None

    @staticmethod
    def resolve_stato_display(obj) -> str:
        return obj.get_stato_display()

    @staticmethod
    def resolve_mod133_esito(obj):
        try:
            return obj.mod133.esito
        except Exception:
            return None


class EventoOut(Schema):
    timestamp: datetime
    stato_da: str
    stato_a: str
    trigger: str
    attore: Optional[str] = None
    payload: dict

    @staticmethod
    def resolve_attore(obj):
        return str(obj.attore) if obj.attore_id else None


class TransizioneIn(Schema):
    azione: str
    motivo: str = ""
    errore: Optional[dict] = None
    master: Optional[int] = None  # id della Specifica master (per marca_duplicato)


class TransizioneOut(Schema):
    ok: bool
    stato: Optional[str] = None
    error: Optional[str] = None


@api.get("/specifiche", response=List[SpecificaOut])
def lista_specifiche(
    request, q: str = "", stato: str = "", cliente: str = "", tag: str = "",
    tipo: str = "", storico: bool = False, dal: Optional[date] = None,
    al: Optional[date] = None, limit: int = 500,
):
    qs = Specifica.objects.all().select_related("mod133")
    if not storico:
        qs = qs.filter(stato__in=C.STATI_ATTIVI)
    if stato:
        qs = qs.filter(stato=stato)
    if tipo:
        qs = qs.filter(tipo=tipo)
    if cliente:
        qs = qs.filter(cliente__icontains=cliente)
    if tag:
        qs = qs.filter(tag__icontains=tag)
    if q:
        qs = qs.filter(Q(codice__icontains=q) | Q(titolo__icontains=q))
    if dal:
        qs = qs.filter(data_inserimento__date__gte=dal)
    if al:
        qs = qs.filter(data_inserimento__date__lte=al)
    return list(qs.order_by("-data_inserimento", "codice")[: max(1, min(limit, 1000))])


@api.get("/specifiche/{spec_id}", response=SpecificaOut)
def dettaglio_specifica(request, spec_id: int):
    return get_object_or_404(Specifica, id=spec_id)


@api.get("/specifiche/{spec_id}/eventi", response=List[EventoOut])
def eventi_specifica(request, spec_id: int):
    spec = get_object_or_404(Specifica, id=spec_id)
    return list(spec.eventi.all())


@api.post("/specifiche/{spec_id}/transizione", response=TransizioneOut)
def transizione_specifica(request, spec_id: int, payload: TransizioneIn):
    spec = get_object_or_404(Specifica, id=spec_id)
    if payload.azione not in _TRANSIZIONI_API:
        return api.create_response(request, {"ok": False, "error": "Azione non valida."}, status=400)
    metodo = getattr(spec, payload.azione, None)
    if not callable(metodo):
        return api.create_response(request, {"ok": False, "error": "Azione non disponibile."}, status=400)

    kwargs = {"attore": request.user}
    if payload.azione == "sospendi":
        kwargs.update(motivo=payload.motivo, data=date.today())
    elif payload.azione in ("ripristina", "annulla", "respingi_flow_down"):
        kwargs.update(motivo=payload.motivo)
    elif payload.azione == "errore_tecnico":
        kwargs.update(errore=payload.errore or {"messaggio": payload.motivo or "errore"})
    elif payload.azione == "marca_duplicato":
        # La master va indicata (Matrice T2): impostata qui sull'istanza, validata prima.
        if payload.master:
            if payload.master == spec.id:
                return api.create_response(request, {"ok": False, "error": "Una specifica non può essere duplicato di se stessa."}, status=400)
            if not Specifica.objects.filter(pk=payload.master).exists():
                return api.create_response(request, {"ok": False, "error": "Specifica master inesistente."}, status=400)
            spec.master_id = payload.master
        kwargs.update(motivo=payload.motivo)

    try:
        metodo(**kwargs)
        spec.save()
    except (TransitionNotAllowed, ValidationError) as exc:
        return api.create_response(request, {"ok": False, "error": str(exc)}, status=400)
    return {"ok": True, "stato": spec.stato}
