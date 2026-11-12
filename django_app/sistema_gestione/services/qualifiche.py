"""Collegamento con Formazione: le qualifiche del personale viste dal Sistema di gestione.

Il dato resta in Anagrafica (``DipendenteQualifica``): qui si legge soltanto, con le
stesse regole del cruscotto Qualifiche (qualifica corrente per persona e tipo, senza
i cessati).
"""
from __future__ import annotations

from django.urls import NoReverseMatch, reverse

from core.operational_roles import get_legacy_anagrafica_id

from .programma import impostazione

CHIAVE_TIPO_AUDITOR = "sistema_gestione.auditor_tipo_qualifica"


def tipo_auditor_id() -> int | None:
    """Il tipo di qualifica che vale come «auditor», scelto nelle impostazioni."""
    valore = (impostazione(CHIAVE_TIPO_AUDITOR) or "").strip()
    return int(valore) if valore.isdigit() else None


def _url_persona(legacy_id: int) -> str:
    try:
        return reverse("anagrafica:dipendente_detail", args=[legacy_id])
    except NoReverseMatch:
        return ""


def qualifica_auditor(auditor) -> dict | None:
    """Lo stato della qualifica dell'auditor interno in Formazione; ``None`` se non c'è collegamento."""
    tipo_id = tipo_auditor_id()
    if not tipo_id or not auditor.interno or not auditor.user_id:
        return None
    from anagrafica.models import DipendenteQualifica

    legacy_id = get_legacy_anagrafica_id(auditor.user)
    vuota = {"trovata": False, "scadenza": None, "scaduta": False, "in_scadenza": False}
    if not legacy_id:
        return {**vuota, "url": ""}
    qualifica = (DipendenteQualifica.objects.filter(legacy_anagrafica_id=legacy_id, tipo_id=tipo_id)
                 .order_by("-data_conseguimento", "-pk").first())
    if qualifica is None:
        return {**vuota, "url": _url_persona(legacy_id)}
    return {"trovata": True, "scadenza": qualifica.data_scadenza, "scaduta": qualifica.is_scaduta,
            "in_scadenza": qualifica.in_scadenza, "url": _url_persona(legacy_id)}


def copertura_qualifiche(tipi) -> list[dict]:
    """Per ogni tipo di qualifica: quante valide, in scadenza (60 giorni) e scadute fra il personale in forza."""
    tipi = list(tipi)
    if not tipi:
        return []
    from anagrafica.models import DipendenteQualifica
    from anagrafica.reportistica.dati import filtra_in
    from anagrafica.services.requisiti import id_qualifiche_correnti
    from anagrafica.views._helpers import _cessati_legacy_ids

    righe = {t.pk: {"tipo": t, "valide": 0, "in_scadenza": 0, "scadute": 0} for t in tipi}
    cessati = _cessati_legacy_ids()
    correnti = filtra_in(DipendenteQualifica.objects.filter(tipo__in=tipi), "pk", id_qualifiche_correnti())
    for q in correnti:
        if q.legacy_anagrafica_id in cessati:
            continue
        chiave = "scadute" if q.is_scaduta else "in_scadenza" if q.in_scadenza else "valide"
        righe[q.tipo_id][chiave] += 1
    return sorted(righe.values(), key=lambda r: r["tipo"].nome.casefold())
