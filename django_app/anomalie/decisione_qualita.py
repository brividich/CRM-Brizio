"""Decisione qualità e «in carico» per singola anomalia.

Tre blocchi nella gestione dell'anomalia:

1. controllore: la segnalazione (con «Dove sono i pezzi?»);
2. capocommessa: spunte (RDC, segnalare a cliente / terzista / CAR, pezzi precedenti),
   «Segnalato», avanzamento, note e allegati;
3. qualità: numero RDC, «Avanzamento qualità» (lista configurabile), note, allegati,
   «Segnalato» se il capocommessa non l'ha fatto, «Chiudi», «Richiedi info aggiuntive».

``ruoli_in_carico`` dice a chi tocca l'anomalia adesso; ``in_carico_a_me`` lo
confronta con chi guarda. Una sola regola per elenco OP, anomalie e contatori.
"""
from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

AVANZAMENTO_CHIARIMENTI = "In attesa chiarimenti"
AVANZAMENTI_QUALITA_DEFAULT = ["In attesa", AVANZAMENTO_CHIARIMENTI]
LISTA_AVANZAMENTI_QUALITA = "avanzamenti_qualita"
KEY_CC_PUO_CHIUDERE = "anomalie_cc_puo_chiudere"

RUOLO_CC = "cc"
RUOLO_QUALITA = "qualita"
RUOLO_CONTROLLORE = "controllore"
RUOLO_CAR = "car"


def avanzamenti_qualita() -> list[str]:
    """Scelte di «Avanzamento qualità» (Configurazione); «In attesa chiarimenti» c'è sempre.
    Il vuoto («nessuno stato») lo aggiunge la pagina come prima scelta."""
    try:
        from .views import _load_anomalie_lists

        lista = [str(v).strip() for v in (_load_anomalie_lists().get(LISTA_AVANZAMENTI_QUALITA) or []) if str(v).strip()]
    except Exception:
        lista = []
    lista = lista or list(AVANZAMENTI_QUALITA_DEFAULT)
    if AVANZAMENTO_CHIARIMENTI.lower() not in {v.lower() for v in lista}:
        lista.append(AVANZAMENTO_CHIARIMENTI)
    return lista


def cc_puo_chiudere() -> bool:
    """Configurazione: il capocommessa chiude da solo (stato di chiusura o «Chiudi»).
    Spento, chiude solo la qualità (o la regola delle segnalazioni). Acceso di serie."""
    try:
        from core.models import SiteConfig

        raw = str(SiteConfig.get(KEY_CC_PUO_CHIUDERE, "") or "").strip().lower()
    except Exception:
        return True
    return raw not in {"0", "false", "no", "off"}


def salva_cc_puo_chiudere(valore: bool) -> bool:
    from core.models import SiteConfig

    return SiteConfig.set(KEY_CC_PUO_CHIUDERE, "1" if valore else "0",
                          "Anomalie: il capocommessa può chiudere da solo l'anomalia.")


# ── Dati della scheda per molte anomalie ───────────────────────────────────


def info_per_anomalie(ids) -> dict[int, dict]:
    """``{id: info}`` con i dati della scheda e delle richieste aperte che servono
    a ``ruoli_in_carico`` (una query per tabella, mai per riga)."""
    out: dict[int, dict] = {}
    ids = sorted({int(i) for i in ids if i is not None})
    if not ids:
        return out
    try:
        from .automazioni_service import separa_car_scelti
        from .quality_models import AnomaliaRichiestaInfo, AnomaliaSchedaQualita

        for i in range(0, len(ids), 500):
            blocco = ids[i:i + 500]
            for s in AnomaliaSchedaQualita.objects.filter(anomalia_id__in=blocco).values(
                "anomalia_id", "segnala_terzista", "segnala_car", "car_segnalati",
                "segnalato_cliente_il", "segnalato_terzista_il", "segnalato_cliente_ruolo",
                "segnalato_terzista_ruolo", "avanzamento_qualita",
            ):
                out[s["anomalia_id"]] = {
                    "segnala_terzista": bool(s["segnala_terzista"]),
                    "car_assegnati": separa_car_scelti(s["car_segnalati"]) if s["segnala_car"] else [],
                    "segnalato_cliente": s["segnalato_cliente_il"] is not None,
                    "segnalato_terzista": s["segnalato_terzista_il"] is not None,
                    "segnalato_cliente_ruolo": s["segnalato_cliente_ruolo"] or "",
                    "segnalato_terzista_ruolo": s["segnalato_terzista_ruolo"] or "",
                    "avanzamento_qualita": s["avanzamento_qualita"] or "",
                    "richiesta_aperta": [],
                }
            for r in AnomaliaRichiestaInfo.objects.filter(anomalia_id__in=blocco, risposta_il__isnull=True):
                info = out.setdefault(r.anomalia_id, _info_vuota())
                for d in r.destinatari or []:
                    if d not in info["richiesta_aperta"]:
                        info["richiesta_aperta"].append(d)
    except Exception:
        logger.warning("anomalie: dati di «in carico» non letti", exc_info=True)
    return out


def _info_vuota() -> dict:
    return {"segnala_terzista": False, "car_assegnati": [], "segnalato_cliente": False, "segnalato_terzista": False,
            "segnalato_cliente_ruolo": "", "segnalato_terzista_ruolo": "", "avanzamento_qualita": "",
            "richiesta_aperta": []}


# ── A chi tocca ────────────────────────────────────────────────────────────


def ruoli_in_carico(row: dict, info: dict | None) -> set[str]:
    """Ruoli che hanno l'anomalia in carico adesso.

    - chiusa: nessuno;
    - richiesta di info aperta: chi deve rispondere (capocommessa e/o controllore);
    - senza decisione del capocommessa, o rimandata con «In attesa di ulteriori
      informazioni»: capocommessa;
    - in attesa della risposta del cliente / terzista: chi ha fatto la segnalazione;
    - altrimenti (deciso, aperto): qualità.
    Il CAR ha in carico solo le anomalie che il capocommessa gli ha segnalato.
    """
    from .controllo_service import riga_gestita
    from .segnalato_service import AVANZAMENTO_RISPOSTA_CLIENTE, AVANZAMENTO_RISPOSTA_TERZISTA
    from .views import AVANZAMENTO_INFO_RICHIESTE

    if not row or row.get("chiudere"):
        return set()
    info = info or _info_vuota()
    ruoli: set[str] = set()
    if info.get("car_assegnati"):
        ruoli.add(RUOLO_CAR)
    if info.get("richiesta_aperta"):
        return ruoli | set(info["richiesta_aperta"])
    av = str(row.get("avanzamento") or "").strip().lower()
    if not riga_gestita(row) or av == AVANZAMENTO_INFO_RICHIESTE.lower():
        return ruoli | {RUOLO_CC}
    if av == AVANZAMENTO_RISPOSTA_CLIENTE.lower():
        return ruoli | {info.get("segnalato_cliente_ruolo") or RUOLO_CC}
    if av == AVANZAMENTO_RISPOSTA_TERZISTA.lower():
        return ruoli | {info.get("segnalato_terzista_ruolo") or RUOLO_CC}
    return ruoli | {RUOLO_QUALITA}


def chi_sono(request, capo, car_op=None) -> dict:
    """Ruoli di chi guarda su un OP: capocommessa, qualità, id legacy (controllore), nomi."""
    from .views import AnomalieRoleType, _is_referente_rdc, _op_role_codes_da_persone, _request_legacy_user_id, \
        _request_name_norms

    codici = _op_role_codes_da_persone(request, capo, car_op)
    return {
        "cc": AnomalieRoleType.CAPO_COMMESSA in codici,
        "qualita": _is_referente_rdc(request),
        "legacy_id": _request_legacy_user_id(request),
        "nomi": _request_name_norms(request),
    }


def in_carico_a_me(io: dict, row: dict, info: dict | None) -> bool:
    """L'anomalia è in carico a chi guarda (``io`` da ``chi_sono``)."""
    from .views import _chiave_persona

    ruoli = ruoli_in_carico(row, info)
    if not ruoli:
        return False
    if RUOLO_CC in ruoli and io.get("cc"):
        return True
    if RUOLO_QUALITA in ruoli and io.get("qualita"):
        return True
    if RUOLO_CONTROLLORE in ruoli and io.get("legacy_id") is not None:
        try:
            if int(row.get("created_by_user_id") or 0) == int(io["legacy_id"]):
                return True
        except (TypeError, ValueError):
            pass
    if RUOLO_CAR in ruoli and io.get("nomi"):
        nomi_car = {_chiave_persona(n) for n in (info or {}).get("car_assegnati") or []}
        if {_chiave_persona(n) for n in io["nomi"]} & nomi_car:
            return True
    return False


# ── Richieste di informazioni ──────────────────────────────────────────────


def richieste_payload(anomalia_id) -> list[dict]:
    from .quality_models import AnomaliaRichiestaInfo

    out = []
    for r in AnomaliaRichiestaInfo.objects.filter(anomalia_id=int(anomalia_id)):
        out.append({
            "id": r.pk, "destinatari": r.destinatari or [], "messaggio": r.messaggio,
            "da": r.richiesta_da_display, "il": timezone.localtime(r.created_at).strftime("%d/%m/%Y %H:%M"),
            "aperta": r.aperta, "risposta": r.risposta, "risposta_da": r.risposta_da_display,
            "risposta_il": timezone.localtime(r.risposta_il).strftime("%d/%m/%Y %H:%M") if r.risposta_il else "",
        })
    return out


def registra_risposta_info(anomalia_id: int, testo: str, *, ruolo: str, chi: str) -> list:
    """Risposta del capocommessa o del controllore alle richieste aperte rivolte a lui.

    Chiuse tutte, l'anomalia torna alla qualità: «In attesa chiarimenti» diventa
    «In attesa». Ritorna le richieste chiuse.
    """
    from .qualita_service import get_or_create_scheda
    from .quality_models import AnomaliaRichiestaInfo, AnomaliaSchedaQualita

    testo = str(testo or "").strip()[:4000]
    if not testo:
        return []
    chiuse = []
    adesso = timezone.now()
    for r in AnomaliaRichiestaInfo.objects.filter(anomalia_id=int(anomalia_id), risposta_il__isnull=True):
        if ruolo not in (r.destinatari or []):
            continue
        r.risposta, r.risposta_da_display, r.risposta_ruolo, r.risposta_il = testo, (chi or "")[:200], ruolo, adesso
        r.save(update_fields=["risposta", "risposta_da_display", "risposta_ruolo", "risposta_il"])
        chiuse.append(r)
    if chiuse and not AnomaliaRichiestaInfo.objects.filter(anomalia_id=int(anomalia_id),
                                                           risposta_il__isnull=True).exists():
        scheda, _ = get_or_create_scheda(int(anomalia_id))
        if scheda is not None and scheda.avanzamento_qualita.strip().lower() == AVANZAMENTO_CHIARIMENTI.lower():
            AnomaliaSchedaQualita.objects.filter(pk=scheda.pk).update(avanzamento_qualita="In attesa", updated_at=adesso)
    return chiuse
