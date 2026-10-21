"""Riordino di reparti e aree senza scollegare le persone.

Il reparto di una persona vive in tre posti (testo legacy, testo della scheda,
FK all'area): qui ogni spostamento passa dall'unico punto che li scrive insieme
e li storicizza (``_sync_aziendale_from_reparto``), più la riga legacy quando il
reparto cambia davvero.

- ``sposta_persona``: la persona va in un'area (e nel suo reparto);
- ``rinomina_reparto``: il reparto cambia nome; i testi *vivi* che lo citano
  (schede, riga legacy, mappatura capi, campagne di refresh aperte) seguono,
  quelli storici (assegnazioni, pratiche passate) restano com'erano;
- ``accorpa_area``: un'area confluisce in un'altra; le persone passano, l'area
  si spegne (non si cancella: FK storiche e statistiche restano valide).
"""
from __future__ import annotations

from django.db import transaction

from ..models import AreaAziendale, DipendenteAnagraficaAziendale, Reparto


def _riga_legacy(legacy_id: int) -> dict | None:
    from core.legacy_anagrafica import fetch_anagrafica_rows

    righe = fetch_anagrafica_rows(ids=[legacy_id])
    return righe[0] if righe else None


def _scrivi_reparto_legacy(dip: dict, legacy_id: int, reparto: str) -> None:
    from core.legacy_anagrafica import upsert_anagrafica_dipendente

    upsert_anagrafica_dipendente(
        row_id=legacy_id,
        aliasusername=dip.get("aliasusername") or "",
        nome=dip.get("nome") or "",
        cognome=dip.get("cognome") or "",
        reparto=reparto,
        mansione=dip.get("mansione") or "",
        ruolo=dip.get("ruolo") or "",
        matricola=dip.get("matricola") or "",
        email=dip.get("email") or "",
        email_notifica=dip.get("email_notifica") or "",
        attivo=bool(dip.get("attivo", True)),
    )


@transaction.atomic
def sposta_persona(legacy_id: int, area: AreaAziendale, *, user=None, data=None) -> bool:
    """La persona va nell'area (e nel reparto dell'area). True se è cambiato qualcosa."""
    from ..models import DipendenteCambiamentoOrganizzativo
    from ..views import _registra_cambiamento, _sync_aziendale_from_reparto

    if area.reparto_id is None:
        raise ValueError(f"L'area «{area.nome}» non ha un reparto.")
    reparto = area.reparto.nome
    az = DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=legacy_id).first()
    if az is not None and az.area_aziendale_id == area.pk and (az.area or "").strip() == reparto:
        return False
    dip = _riga_legacy(legacy_id)
    if dip is not None:
        prima = (dip.get("reparto") or "").strip()
        if prima != reparto:
            _scrivi_reparto_legacy(dip, legacy_id, reparto)
            _registra_cambiamento(legacy_id, DipendenteCambiamentoOrganizzativo.TIPO_REPARTO,
                                  prima, reparto, user, data_effetto=data)
    _sync_aziendale_from_reparto(legacy_id, reparto, area_aziendale_id=area.pk, saved_by=user,
                                 data_decorrenza=data)
    return True


@transaction.atomic
def rinomina_reparto(reparto: Reparto, nuovo_nome: str, *, user=None) -> dict:
    nuovo_nome = " ".join((nuovo_nome or "").split())[:100]
    if not nuovo_nome:
        raise ValueError("Il nome del reparto non può essere vuoto.")
    vecchio = reparto.nome
    if vecchio == nuovo_nome:
        return {"schede": 0, "legacy": 0}
    if Reparto.objects.filter(nome__iexact=nuovo_nome).exclude(pk=reparto.pk).exists():
        raise ValueError(f"Esiste già un reparto «{nuovo_nome}».")
    reparto.nome = nuovo_nome
    reparto.save(update_fields=["nome"])
    schede = DipendenteAnagraficaAziendale.objects.filter(area__iexact=vecchio).update(area=nuovo_nome)
    legacy = 0
    from core.legacy_anagrafica import fetch_anagrafica_rows

    for dip in fetch_anagrafica_rows():
        if (dip.get("reparto") or "").strip().casefold() == vecchio.casefold() and dip.get("id"):
            _scrivi_reparto_legacy(dip, int(dip["id"]), nuovo_nome)
            legacy += 1
    try:
        from core.models import RepartoCapoMapping

        RepartoCapoMapping.objects.filter(reparto__iexact=vecchio).update(reparto=nuovo_nome)
    except Exception:  # tabella di compatibilità: se manca non blocca la rinomina
        pass
    from ..models import CampagnaRefresh

    CampagnaRefresh.objects.filter(reparto__iexact=vecchio, stato=CampagnaRefresh.STATO_APERTA).update(
        reparto=nuovo_nome)
    return {"schede": schede, "legacy": legacy}


@transaction.atomic
def accorpa_area(vecchia: AreaAziendale, ospite: AreaAziendale, *, user=None) -> int:
    """Le persone dell'area ``vecchia`` passano a ``ospite``; la vecchia si spegne."""
    if vecchia.pk == ospite.pk:
        return 0
    n = 0
    for lid in list(DipendenteAnagraficaAziendale.objects.filter(area_aziendale=vecchia)
                    .values_list("legacy_anagrafica_id", flat=True)):
        if sposta_persona(lid, ospite, user=user):
            n += 1
    from ..models import CompetenzaSkm

    CompetenzaSkm.objects.filter(area=vecchia).update(area=ospite, reparto=ospite.reparto)
    vecchia.is_active = False
    vecchia.save(update_fields=["is_active"])
    return n
