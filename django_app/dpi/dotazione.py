"""La situazione DPI di una persona: cosa ha in carico, cosa scade, cosa le manca.

Una sola definizione per dashboard, nuova richiesta e filtro della gestione: la scadenza
viene da ``ConsegnaDPI.semaforo_scadenza``, le consegne sostituite non contano, e per
categoria vale l'ultima consegna (come nel report di conformita').
"""
from __future__ import annotations

import logging
from datetime import timedelta
from urllib.parse import urlencode

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .models import ConsegnaDPI, RichiestaDPI, StatoRichiesta

logger = logging.getLogger(__name__)

GIORNI_AVVISO = 30
SCADUTI = "scaduti"
IN_SCADENZA = "in_scadenza"
FILTRI_SCADENZA = ((SCADUTI, "Scaduti"), (IN_SCADENZA, f"In scadenza ({GIORNI_AVVISO} giorni)"))

_ORDINE_SEMAFORO = {"rosso": 0, "arancione": 1, "verde": 2, "": 3}


def filtro_scadenza(chiave: str, oggi=None) -> Q:
    """Q sulle richieste consegnate, non sostituite, scadute o in scadenza."""
    oggi = oggi or timezone.localdate()
    base = Q(
        stato=StatoRichiesta.CONSEGNATA,
        consegna__sostituita_da__isnull=True,
        consegna__data_scadenza_stimata__isnull=False,
    )
    if chiave == SCADUTI:
        return base & Q(consegna__data_scadenza_stimata__lt=oggi)
    return base & Q(
        consegna__data_scadenza_stimata__gte=oggi,
        consegna__data_scadenza_stimata__lte=oggi + timedelta(days=GIORNI_AVVISO),
    )


def url_richiesta(*, categoria_id, tipo_id=None, modello_id=None, taglia_id=None, motivo: str = "") -> str:
    """Link alla nuova richiesta gia' compilata."""
    parametri = {"categoria": categoria_id, "tipo": tipo_id, "modello": modello_id, "taglia": taglia_id, "motivo": motivo}
    return reverse("dpi:nuova") + "?" + urlencode({k: v for k, v in parametri.items() if v})


def _passo(richiesta: RichiestaDPI) -> str:
    if richiesta.is_pronta_ritiro:
        return "È pronta: passa in magazzino a ritirarla."
    if richiesta.stato == StatoRichiesta.APPROVATA:
        return "Approvata: il magazzino la sta preparando."
    return "In attesa dell'approvazione del responsabile."


def _stesso_dpi(richiesta: RichiestaDPI, altra: RichiestaDPI) -> bool:
    if richiesta.categoria_id != altra.categoria_id:
        return False
    return not (richiesta.tipo_dpi_id and altra.tipo_dpi_id) or richiesta.tipo_dpi_id == altra.tipo_dpi_id


def _categorie_previste(legacy_id: int) -> list:
    """Categorie richieste dalla mansione di rischio. Un errore non rompe la pagina."""
    try:
        from anagrafica.services import mansionario

        return list(mansionario.requisiti_dipendente(legacy_id)["dpi"])
    except Exception:  # noqa: BLE001
        logger.exception("Profilo di rischio non calcolato per la dotazione DPI")
        return []


def dotazione(legacy_id: int) -> dict:
    """DPI in carico alla persona, richieste in corso e DPI previsti che non ha."""
    oggi = timezone.localdate()
    relazioni = ("categoria", "tipo_dpi", "modello_dpi", "taglia_dpi")
    aperte = list(
        RichiestaDPI.objects.filter(
            richiedente_legacy_id=legacy_id, stato__in=[StatoRichiesta.INVIATA, StatoRichiesta.APPROVATA]
        ).select_related(*relazioni).order_by("-created_at")
    )
    consegne = (
        ConsegnaDPI.objects.filter(
            richiesta__richiedente_legacy_id=legacy_id,
            richiesta__stato=StatoRichiesta.CONSEGNATA,
            sostituita_da__isnull=True,
        )
        .select_related(*(f"richiesta__{r}" for r in relazioni))
        .order_by("-data_consegna", "-created_at")
    )
    righe = []
    for c in consegne:
        r = c.richiesta
        semaforo = c.semaforo_scadenza
        giorni = (c.data_scadenza_stimata - oggi).days if c.data_scadenza_stimata else None
        righe.append({
            "consegna": c,
            "richiesta": r,
            "semaforo": semaforo,
            "giorni": giorni,
            "giorni_fa": -giorni if giorni is not None and giorni < 0 else None,
            "ricambio_aperto": next((a for a in aperte if _stesso_dpi(a, r)), None),
            "url_ricambio": url_richiesta(
                categoria_id=r.categoria_id, tipo_id=r.tipo_dpi_id, modello_id=r.modello_dpi_id, taglia_id=r.taglia_dpi_id,
                motivo="scadenza" if semaforo in ("rosso", "arancione") else "",
            ),
        })
    coperte = {r["richiesta"].categoria_id for r in righe} | {a.categoria_id for a in aperte}
    mancanti = [
        {"categoria": c, "url": url_richiesta(categoria_id=c.pk, motivo="prima")}
        for c in _categorie_previste(legacy_id)
        if c.pk not in coperte and c.is_active
    ]
    return {
        "righe": sorted(righe, key=lambda x: _ORDINE_SEMAFORO.get(x["semaforo"], 3)),
        "aperte": [{"richiesta": a, "passo": _passo(a)} for a in aperte],
        "mancanti": mancanti,
        "n_da_sostituire": sum(1 for x in righe if x["semaforo"] in ("rosso", "arancione") and not x["ricambio_aperto"]),
    }


def aiuti_per_categoria(situazione: dict) -> dict[int, dict]:
    """Per ogni categoria: l'ultima consegna (per «come l'ultima volta») e le richieste aperte."""
    aiuti: dict[int, dict] = {}
    for x in sorted(situazione["righe"], key=lambda x: x["consegna"].data_consegna, reverse=True):
        r, c = x["richiesta"], x["consegna"]
        if r.categoria_id in aiuti:
            continue
        pezzi = [r.tipo_dpi and r.tipo_dpi.nome, r.modello_dpi and r.modello_dpi.nome, r.taglia_dpi and f"taglia {r.taglia_dpi.valore}"]
        aiuti[r.categoria_id] = {
            "aperte": [],
            "ultima": {
                "tipo": r.tipo_dpi_id, "modello": r.modello_dpi_id, "taglia": r.taglia_dpi_id,
                "etichetta": ", ".join(p for p in pezzi if p),
                "data": c.data_consegna.strftime("%d-%m-%Y"),
                "scadenza": c.data_scadenza_stimata.strftime("%d-%m-%Y") if c.data_scadenza_stimata else "",
                "semaforo": x["semaforo"],
            },
        }
    for x in situazione["aperte"]:
        a = x["richiesta"]
        aiuti.setdefault(a.categoria_id, {"aperte": [], "ultima": None})["aperte"].append(
            {"numero": a.numero, "stato": a.label_stato}
        )
    return aiuti


def etichetta_categoria(aiuto: dict | None) -> dict | None:
    """Stato sulla scheda della categoria nella nuova richiesta."""
    if not aiuto:
        return None
    if aiuto["aperte"]:
        return {"tono": "blu", "testo": "Già richiesto"}
    ultima = aiuto["ultima"]
    if ultima["semaforo"] == "rosso":
        return {"tono": "rosso", "testo": "Scaduto"}
    if ultima["semaforo"] == "arancione":
        return {"tono": "arancione", "testo": "In scadenza"}
    return {"tono": "verde", "testo": "In dotazione"}
