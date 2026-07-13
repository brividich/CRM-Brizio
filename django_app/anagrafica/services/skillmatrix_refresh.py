"""F6 — Refresh semestrale delle abilitazioni macchina (campagna CAR).

Il CAR rivaluta, sul **proprio reparto**, le abilitazioni in lista (① conferma
invariati / modifica livello / rimuovi dalla lista) e può aggiungere nuove
abilitazioni (② aggiunte manuali). Ogni conferma/modifica/aggiunta produce uno
**scatto** in ``AbilitazioneMacchinaStorico`` (fonte ``refresh``) e sposta in avanti
``prossima_revisione`` di ``periodicita_refresh_mesi``.

La **campagna** (``CampagnaRefresh``) è solo l'innesco (trigger) della tornata; il
merito della rivalutazione è del CAR. L'arretrato (revisione scaduta) è **visibile
ma non bloccante**.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from urllib.parse import urlencode

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from ..models import (
    AbilitazioneMacchina,
    AbilitazioneMacchinaStorico,
    CampagnaRefresh,
    CompetenzaSkm,
    LivelloSkm,
    SkillMatrixConfig,
)

logger = logging.getLogger(__name__)


def _asset_ids_reparto(reparto: str) -> list[int]:
    return list(
        CompetenzaSkm.objects
        .filter(tipo=CompetenzaSkm.TIPO_MACCHINA, asset__isnull=False, asset__reparto=reparto)
        .values_list("asset_id", flat=True)
    )


def abilitazioni_reparto(reparto: str):
    """Abilitazioni in lista sulle macchine del reparto (gruppo ① da rivalutare)."""
    ids = _asset_ids_reparto(reparto)
    if not ids:
        return AbilitazioneMacchina.objects.none()
    return (
        AbilitazioneMacchina.objects
        .filter(asset_id__in=ids, in_lista=True)
        .select_related("asset").order_by("legacy_anagrafica_id", "asset__name")
    )


def _get_or_crea_campagna(reparto: str, *, periodo_inizio=None, avviatore_ruolo: str = "",
                          scadenza=None) -> tuple[CampagnaRefresh, bool]:
    periodo_inizio = periodo_inizio or timezone.localdate()
    return CampagnaRefresh.objects.get_or_create(
        reparto=reparto, stato=CampagnaRefresh.STATO_APERTA,
        defaults={"periodo_inizio": periodo_inizio, "avviatore_ruolo": avviatore_ruolo,
                  "scadenza": scadenza},
    )


def apri_campagna(reparto: str, *, periodo_inizio=None, avviatore_ruolo: str = "",
                  scadenza=None) -> CampagnaRefresh:
    """Apre (o riusa) la campagna aperta del reparto. Idempotente."""
    camp, _ = _get_or_crea_campagna(reparto, periodo_inizio=periodo_inizio,
                                    avviatore_ruolo=avviatore_ruolo, scadenza=scadenza)
    return camp


def _scatto(ab: AbilitazioneMacchina, data, car_legacy_id, note: str) -> None:
    AbilitazioneMacchinaStorico.objects.create(
        legacy_anagrafica_id=ab.legacy_anagrafica_id, asset_id=ab.asset_id,
        livello=ab.livello, data_rilevazione=data,
        fonte=AbilitazioneMacchinaStorico.FONTE_REFRESH,
        car_legacy_id=car_legacy_id, note=note,
    )


def _prossima_revisione(oggi, config: SkillMatrixConfig):
    return oggi + timedelta(days=int(config.periodicita_refresh_mesi * 30.44))


def applica_refresh(*, reparto: str, decisioni: dict, car_legacy_id=None, oggi=None,
                    apply: bool = True, campagna: CampagnaRefresh | None = None,
                    chiudi_campagna: bool = False) -> dict:
    """Applica la rivalutazione del gruppo ①.

    ``decisioni``: ``{abilitazione_id: {"azione": "conferma|modifica|rimuovi",
    "livello": "U"}}``. Scrive scatti storico e sposta ``prossima_revisione``.
    """
    oggi = oggi or timezone.localdate()
    config = SkillMatrixConfig.get_instance()
    nuova_rev = _prossima_revisione(oggi, config)
    stats = {"apply": apply, "confermate": 0, "modificate": 0, "rimosse": 0}
    abil = {a.id: a for a in abilitazioni_reparto(reparto)}

    with transaction.atomic():
        for ab_id, dec in decisioni.items():
            ab = abil.get(int(ab_id))
            if ab is None:
                continue
            azione = (dec.get("azione") or "conferma").strip()
            if azione == "rimuovi":
                stats["rimosse"] += 1
                if apply:
                    ab.in_lista = False
                    ab.prossima_revisione = nuova_rev
                    ab.save(update_fields=["in_lista", "prossima_revisione", "updated_at"])
                    _scatto(ab, oggi, car_legacy_id, "Refresh: rimosso dalla lista")
                continue
            nuovo = (dec.get("livello") or ab.livello).strip().upper()
            if nuovo not in dict(LivelloSkm.choices):
                nuovo = ab.livello
            cambiato = nuovo != ab.livello
            stats["modificate" if cambiato else "confermate"] += 1
            if apply:
                ab.livello = nuovo
                ab.prossima_revisione = nuova_rev
                ab.save(update_fields=["livello", "prossima_revisione", "updated_at"])
                _scatto(ab, oggi, car_legacy_id,
                        "Refresh: modifica livello" if cambiato else "Refresh: confermato invariato")
        if apply and chiudi_campagna and campagna is not None:
            campagna.stato = CampagnaRefresh.STATO_CHIUSA
            campagna.periodo_fine = oggi
            campagna.save(update_fields=["stato", "periodo_fine", "updated_at"])
    return stats


def aggiungi_abilitazione(*, legacy_anagrafica_id: int, asset_id: int, livello: str,
                          car_legacy_id=None, oggi=None, conteggiabile=True) -> AbilitazioneMacchina:
    """Aggiunta manuale (gruppo ②): crea/riattiva un'abilitazione + scatto storico."""
    oggi = oggi or timezone.localdate()
    config = SkillMatrixConfig.get_instance()
    livello = (livello or "").strip().upper()
    if livello not in dict(LivelloSkm.choices):
        raise ValueError(f"Livello non valido: {livello!r}")
    ab, _ = AbilitazioneMacchina.objects.update_or_create(
        legacy_anagrafica_id=legacy_anagrafica_id, asset_id=asset_id,
        defaults={
            "livello": livello, "in_lista": True,
            "stato": AbilitazioneMacchina.STATO_ATTIVA,
            "conteggiabile_nel_carico": conteggiabile,
            "car_legacy_id": car_legacy_id,
            "prossima_revisione": _prossima_revisione(oggi, config),
        },
    )
    _scatto(ab, oggi, car_legacy_id, "Refresh: aggiunta manuale")
    return ab


def arretrati_reparto(reparto: str, *, oggi=None) -> int:
    """Conteggio abilitazioni con revisione scaduta (arretrato, NON bloccante)."""
    oggi = oggi or timezone.localdate()
    return abilitazioni_reparto(reparto).filter(prossima_revisione__lt=oggi).count()


# ---------------------------------------------------------------------------
# F10 — scadenzario abilitazioni + avvio refresh HR->CAR
# ---------------------------------------------------------------------------
def scadenzario_reparti(oggi=None, config: SkillMatrixConfig | None = None) -> list[dict]:
    """Stato del refresh per reparto (derivato da prossima_revisione, in_lista).

    Un dict per reparto con almeno un'abilitazione in lista su una macchina catalogata.
    Stati: 'scaduto' (>=1 revisione < oggi), 'in_arrivo' (min non-scaduta <= oggi+preavviso),
    'ok' altrimenti. Ordinati per urgenza.
    """
    oggi = oggi or timezone.localdate()
    config = config or SkillMatrixConfig.get_instance()
    soglia = oggi + timedelta(days=int(config.preavviso_refresh_giorni))

    reparto_per_asset = {}
    for c in (CompetenzaSkm.objects
              .filter(tipo=CompetenzaSkm.TIPO_MACCHINA, asset__isnull=False)
              .select_related("asset")):
        rep = (c.asset.reparto or "").strip()
        if rep:
            reparto_per_asset[c.asset_id] = rep
    if not reparto_per_asset:
        return []

    agg: dict[str, dict] = {}
    for a in (AbilitazioneMacchina.objects
              .filter(in_lista=True, asset_id__in=list(reparto_per_asset.keys()))):
        rep = reparto_per_asset.get(a.asset_id)
        if not rep:
            continue
        d = agg.setdefault(rep, {"n_totali": 0, "n_scadute": 0, "n_in_arrivo": 0,
                                 "prossima_revisione": None})
        d["n_totali"] += 1
        pr = a.prossima_revisione
        if pr is not None and pr < oggi:
            d["n_scadute"] += 1
        elif pr is not None and pr <= soglia:
            d["n_in_arrivo"] += 1
        if pr is not None and (d["prossima_revisione"] is None or pr < d["prossima_revisione"]):
            d["prossima_revisione"] = pr

    aperte = {c.reparto: c for c in
              CampagnaRefresh.objects.filter(stato=CampagnaRefresh.STATO_APERTA)}

    out = []
    for rep, d in agg.items():
        stato = "scaduto" if d["n_scadute"] else ("in_arrivo" if d["n_in_arrivo"] else "ok")
        camp = aperte.get(rep)
        out.append({
            "reparto": rep,
            "prossima_revisione": d["prossima_revisione"],
            "n_totali": d["n_totali"],
            "n_scadute": d["n_scadute"],
            "n_in_arrivo": d["n_in_arrivo"],
            "stato": stato,
            "campagna_aperta": camp is not None,
            "campagna_id": camp.id if camp else None,
            "campagna_periodo_inizio": camp.periodo_inizio if camp else None,
        })

    rank = {"scaduto": 0, "in_arrivo": 1, "ok": 2}
    out.sort(key=lambda r: (rank[r["stato"]], -r["n_scadute"],
                            r["prossima_revisione"] or date.max, r["reparto"]))
    return out


def _risolvi_car(reparto: str) -> tuple[int | None, str]:
    """(caporeparto_legacy_id, email_notifica) del CAR del reparto, o (None, "")."""
    from ..models import Reparto
    rep = Reparto.objects.filter(nome__iexact=(reparto or "").strip()).first()
    if not rep or not rep.caporeparto_legacy_id:
        return (None, "")
    car_id = int(rep.caporeparto_legacy_id)
    email = ""
    try:
        from core.legacy_models import AnagraficaDipendente
        email = (AnagraficaDipendente.objects
                 .filter(id=car_id).values_list("email_notifica", flat=True).first()) or ""
    except Exception:
        logger.debug("Email CAR non risolta per reparto=%s", reparto, exc_info=True)
    return (car_id, str(email).strip())


def _notifica_car(reparto: str) -> None:
    """In-app + email best-effort al CAR. Nessun errore propagato."""
    car_id, car_email = _risolvi_car(reparto)
    n_da = abilitazioni_reparto(reparto).count()
    url = reverse("anagrafica:skm_refresh") + "?" + urlencode({"reparto": reparto})
    if car_id:
        try:
            from core.notifiche import invia_notifica
            invia_notifica(
                car_id, "skm_refresh",
                f"Refresh abilitazioni macchina avviato per il reparto «{reparto}»: "
                f"{n_da} abilitazioni da rivalutare.", url)
        except Exception:
            logger.warning("Notifica in-app CAR fallita reparto=%s", reparto, exc_info=True)
    if car_email:
        try:
            from core.email_utils import send_hub_mail
            send_hub_mail(
                f"Refresh abilitazioni macchina — reparto {reparto}",
                f"È stato avviato il refresh semestrale delle abilitazioni macchina del "
                f"reparto «{reparto}».\n\nAbilitazioni da rivalutare: {n_da}.\n\n"
                f"Apri la pagina di rivalutazione dal portale NOVICROM HUB.",
                [car_email], email_type="Anagrafica HR",
                section_label="Refresh abilitazioni macchina", fail_silently=True)
        except Exception:
            logger.warning("Email CAR fallita reparto=%s", reparto, exc_info=True)


def avvia_refresh(*, reparto: str, avviatore_ruolo: str = "", avviatore_legacy_id=None,
                  oggi=None) -> tuple[CampagnaRefresh, bool]:
    """HR "dà il via": apre la campagna del reparto (idempotente) e, solo se appena
    creata, notifica il CAR. L'apertura non è mai annullata da un errore di notifica."""
    reparto = (reparto or "").strip()
    if not reparto:
        raise ValueError("reparto obbligatorio")
    camp, created = _get_or_crea_campagna(reparto, periodo_inizio=oggi,
                                          avviatore_ruolo=avviatore_ruolo)
    if created:
        _notifica_car(reparto)
    return camp, created


def campagne_da_gestire(car_legacy_id) -> list[dict]:
    """Campagne di refresh APERTE dei reparti di cui il legacy_id è caporeparto (CAR).
    Read-only, per la home 'Cose da gestire'."""
    if not car_legacy_id:
        return []
    from ..models import Reparto
    reparti = list(Reparto.objects
                   .filter(caporeparto_legacy_id=int(car_legacy_id))
                   .values_list("nome", flat=True))
    if not reparti:
        return []
    out = []
    for c in CampagnaRefresh.objects.filter(stato=CampagnaRefresh.STATO_APERTA,
                                            reparto__in=reparti):
        out.append({
            "reparto": c.reparto,
            "campagna_id": c.id,
            "n_da_rivalutare": abilitazioni_reparto(c.reparto).count(),
            "url": reverse("anagrafica:skm_refresh") + "?" + urlencode({"reparto": c.reparto}),
        })
    return out
