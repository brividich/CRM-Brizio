"""Tempi delle anomalie: risposta del capocommessa, attesa del cliente, esecuzione
dell'azione, risoluzione. Unica fonte per dettaglio, statistiche, NC ed export.

Le date degli eventi stanno nella scheda qualita' (``AnomaliaSchedaQualita``) e le
scrive :func:`aggiorna_tempi`, chiamata a ogni salvataggio dell'anomalia (portale,
controllo, link della mail, riapertura) tramite ``qualita_service.sync_da_anomalia``.

Si contano solo i **giorni lavorativi** (lunedi'-venerdi', festivi nazionali esclusi,
``core.calendario_it``): un giorno lavorativo pieno vale 1, una parte di giorno la sua
frazione. Sabati, domeniche e festivi valgono 0.

Inizio di ogni tempo:

* risposta: mail del controllo partita (``AnomaliaControllo.terminato_at``) oppure
  creazione dell'anomalia, se nata fuori da un controllo → prima decisione;
* attesa cliente: stato «In attesa risposta cliente» → risposta registrata o stato
  cambiato;
* esecuzione: prima decisione «Azione di recupero» → azione effettuata;
* risoluzione: creazione → chiusura (dopo una riapertura vale l'ultima chiusura).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from statistics import median

from django.utils import timezone

logger = logging.getLogger(__name__)

AVANZAMENTO_RECUPERO = "Azione di recupero"
AVANZAMENTO_RISPOSTA_CLIENTE = "In attesa risposta cliente"

METRICHE = (
    ("risposta", "Risposta del capocommessa"),
    ("attesa_cliente", "Attesa del cliente"),
    ("esecuzione", "Esecuzione dell'azione"),
    ("risoluzione", "Risoluzione"),
)

MSG_SERVE_AZIONE = (
    "Questa anomalia è in «Azione di recupero»: per chiuderla registra prima l'azione effettuata "
    "(riquadro «Azione effettuata»)."
)


# ── Giorni lavorativi ──────────────────────────────────────────────────────


def _locale(dt) -> datetime:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.strip().replace(" ", "T", 1))
    elif isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime.combine(dt, time.min)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    return timezone.localtime(dt)


def giorni_lavorativi(inizio, fine) -> float | None:
    """Giorni lavorativi fra due istanti (frazioni comprese); None se manca un estremo."""
    from core.calendario_it import festivi_tra, is_lavorativo

    if not inizio or not fine:
        return None
    a, b = _locale(inizio), _locale(fine)
    if b <= a:
        return 0.0
    festivi = festivi_tra(a.date(), b.date())
    totale = 0.0
    giorno: date = a.date()
    while giorno <= b.date():
        if is_lavorativo(giorno, festivi):
            da = a if giorno == a.date() else datetime.combine(giorno, time.min, tzinfo=a.tzinfo)
            fino = b if giorno == b.date() else datetime.combine(giorno + timedelta(days=1), time.min, tzinfo=a.tzinfo)
            totale += max(0.0, (fino - da).total_seconds()) / 86400
        giorno += timedelta(days=1)
    return round(totale, 2)


def etichetta_durata(giorni: float | None) -> str:
    """«3 h» sotto il giorno, «1,5 gg» sopra; «—» se non c'e'."""
    if giorni is None:
        return "—"
    if giorni < 1:
        ore = round(giorni * 24)
        return "meno di 1 h" if ore < 1 else f"{ore} h"
    return f"{giorni:.1f}".replace(".", ",").replace(",0", "") + " gg"


# ── Registrazione degli eventi ─────────────────────────────────────────────


def aggiorna_tempi(scheda, row: dict, *, adesso=None) -> list[str]:
    """Allinea le date degli eventi della scheda allo stato attuale della riga.

    Una data gia' scritta non si sposta, tranne ``chiusa_il`` (azzerata dalla
    riapertura) e l'attesa del cliente (un nuovo ciclo dopo una risposta).
    Ritorna i campi cambiati (gia' salvati).
    """
    from .controllo_service import riga_gestita

    adesso = adesso or timezone.now()
    avanz = str(row.get("avanzamento") or "").strip()
    campi: list[str] = []

    if scheda.prima_decisione_il is None and riga_gestita(row):
        scheda.prima_decisione_il = adesso
        scheda.primo_avanzamento = avanz[:100]
        campi += ["prima_decisione_il", "primo_avanzamento"]

    in_attesa_cliente = avanz.lower() == AVANZAMENTO_RISPOSTA_CLIENTE.lower()
    if in_attesa_cliente and (scheda.attesa_cliente_dal is None or scheda.risposta_cliente_il is not None):
        # Primo invio al cliente, oppure nuova attesa dopo una risposta gia' arrivata.
        scheda.attesa_cliente_dal = adesso
        scheda.risposta_cliente_il = None
        campi += ["attesa_cliente_dal", "risposta_cliente_il"]
    elif not in_attesa_cliente and scheda.attesa_cliente_dal and scheda.risposta_cliente_il is None:
        scheda.risposta_cliente_il = adesso
        campi.append("risposta_cliente_il")

    chiusa = bool(row.get("chiudere"))
    if chiusa and scheda.chiusa_il is None:
        scheda.chiusa_il = adesso
        campi.append("chiusa_il")
    elif not chiusa and scheda.chiusa_il is not None:
        scheda.chiusa_il = None
        campi.append("chiusa_il")

    if campi:
        scheda.save(update_fields=[*dict.fromkeys(campi), "updated_at"])
    return campi


def serve_azione_per_chiudere(anomalia_id: int) -> bool:
    """True se la prima decisione e' stata «Azione di recupero» e manca l'azione effettuata."""
    from .quality_models import AnomaliaSchedaQualita

    scheda = AnomaliaSchedaQualita.objects.filter(anomalia_id=anomalia_id).only(
        "primo_avanzamento", "azione_effettuata_il",
    ).first()
    return bool(
        scheda
        and scheda.primo_avanzamento.strip().lower() == AVANZAMENTO_RECUPERO.lower()
        and scheda.azione_effettuata_il is None
    )


# ── Calcolo ────────────────────────────────────────────────────────────────


def notifiche_il(anomalia_ids) -> dict[int, datetime]:
    """{anomalia_id: istante della mail del controllo} per le anomalie nate in un controllo."""
    from .quality_models import AnomaliaSegnalazioneMeta

    ids = [int(i) for i in anomalia_ids]
    out: dict[int, datetime] = {}
    for i in range(0, len(ids), 500):
        for aid, quando in AnomaliaSegnalazioneMeta.objects.filter(
            anomalia_id__in=ids[i:i + 500], controllo__terminato_at__isnull=False,
        ).values_list("anomalia_id", "controllo__terminato_at"):
            out[int(aid)] = quando
    return out


def tempi_anomalia(*, creata_il, scheda, notificata_il=None, adesso=None) -> dict:
    """Durate in giorni lavorativi; per i tempi ancora aperti ``in_corso`` e' True."""
    adesso = adesso or timezone.now()
    out: dict = {}

    def _metrica(chiave, inizio, fine):
        if not inizio:
            out[chiave] = None
            return
        out[chiave] = {
            "giorni": giorni_lavorativi(inizio, fine or adesso),
            "in_corso": fine is None,
        }

    if scheda is None:
        for chiave, _label in METRICHE:
            out[chiave] = None
        _metrica("risoluzione", creata_il, None)
        return out
    inizio_risposta = notificata_il or creata_il
    _metrica("risposta", inizio_risposta, scheda.prima_decisione_il)
    _metrica("attesa_cliente", scheda.attesa_cliente_dal, scheda.risposta_cliente_il)
    recupero = scheda.primo_avanzamento.strip().lower() == AVANZAMENTO_RECUPERO.lower()
    _metrica("esecuzione", scheda.prima_decisione_il if recupero else None, scheda.azione_effettuata_il)
    _metrica("risoluzione", creata_il, scheda.chiusa_il)
    return out


def tempi_per_anomalie(rows: list[dict], *, adesso=None) -> dict[int, dict]:
    """{id: tempi} per righe legacy con ``id`` e ``created_datetime``."""
    from .quality_models import AnomaliaSchedaQualita

    ids = [int(r["id"]) for r in rows if r.get("id") is not None]
    schede = {s.anomalia_id: s for s in AnomaliaSchedaQualita.objects.filter(anomalia_id__in=ids)} if ids else {}
    notifiche = notifiche_il(ids) if ids else {}
    return {
        int(r["id"]): tempi_anomalia(
            creata_il=r.get("created_datetime"), scheda=schede.get(int(r["id"])),
            notificata_il=notifiche.get(int(r["id"])), adesso=adesso,
        )
        for r in rows if r.get("id") is not None
    }


def soglie() -> dict:
    """Obiettivi in giorni lavorativi (Configurazione → Notifiche → «Orari e soglie»)."""
    from .escalation_config import get_escalation_config

    try:
        cfg = get_escalation_config()
        return {"risposta": cfg["tempi_risposta_gg"], "risoluzione": cfg["tempi_risoluzione_gg"]}
    except Exception:
        from .escalation_config import DEFAULT_TEMPI_RISOLUZIONE_GG, DEFAULT_TEMPI_RISPOSTA_GG

        return {"risposta": DEFAULT_TEMPI_RISPOSTA_GG, "risoluzione": DEFAULT_TEMPI_RISOLUZIONE_GG}


def riepilogo(tempi: dict[int, dict], *, gruppi: dict[int, str] | None = None) -> dict:
    """KPI dei tempi: per metrica mediana e media dei conclusi, quanti in corso,
    % entro l'obiettivo e aperti oltre l'obiettivo (risposta e risoluzione).
    ``gruppi`` ({id: capocommessa}) aggiunge la tabella per gruppo."""
    obiettivi = soglie()

    def _kpi(valori: list[dict], chiave: str) -> dict:
        conclusi = [v["giorni"] for v in valori if v and not v["in_corso"] and v["giorni"] is not None]
        in_corso = [v["giorni"] for v in valori if v and v["in_corso"] and v["giorni"] is not None]
        soglia = obiettivi.get(chiave)
        out = {
            "conclusi": len(conclusi),
            "in_corso": len(in_corso),
            "mediana": round(median(conclusi), 1) if conclusi else None,
            "media": round(sum(conclusi) / len(conclusi), 1) if conclusi else None,
            "soglia": soglia,
            "entro_soglia_pct": None,
            "oltre_soglia_aperti": None,
        }
        if soglia:
            if conclusi:
                out["entro_soglia_pct"] = round(100 * sum(1 for g in conclusi if g <= soglia) / len(conclusi))
            out["oltre_soglia_aperti"] = sum(1 for g in in_corso if g > soglia)
        return out

    metriche = {
        chiave: {"label": label, **_kpi([t.get(chiave) for t in tempi.values()], chiave)}
        for chiave, label in METRICHE
    }
    per_gruppo = []
    if gruppi:
        nomi: dict[str, list[int]] = {}
        for aid, nome in gruppi.items():
            if aid in tempi:
                nomi.setdefault(nome or "—", []).append(aid)
        for nome, ids in sorted(nomi.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            riga = {"nome": nome, "anomalie": len(ids)}
            for chiave in ("risposta", "risoluzione"):
                riga[chiave] = _kpi([tempi[i].get(chiave) for i in ids], chiave)["mediana"]
            per_gruppo.append(riga)
    return {"metriche": metriche, "per_capocommessa": per_gruppo, "soglie": obiettivi, "unita": "giorni lavorativi"}
