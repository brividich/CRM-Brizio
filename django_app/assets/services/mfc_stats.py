"""Statistiche MFC per la scheda asset: solo dati gia' a DB, mai SNMP nella request.

Le letture arrivano dai job di ``contatori`` (consumabili ogni giorno, contatori ogni
mese). Qui si leggono e si interpretano: livelli all'ultima lettura con stima di
esaurimento, pagine stampate per mese (B/N e colore) con trend, ultimo errore SNMP e
avviso quando i dati sono vecchi, invece di mostrarli come attuali.

Query: una per i consumabili (finestra di stima) e una per le letture mensili, per
tutte le MFC dell'asset insieme (gli id sono al massimo ``LINK_LIMIT``).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

#: Consumabili: il job e' giornaliero, oltre questi giorni il dato e' "vecchio".
DEFAULT_GIORNI_CONSUMABILI = 3
#: Contatori: lettura mensile, oltre questi giorni manca almeno un mese.
DEFAULT_GIORNI_CONTATORI = 40
#: Mesi di storico mostrati nel trend pagine.
MESI_TREND = 12


def giorni_soglia_consumabili() -> int:
    return int(getattr(settings, "ASSETS_MFC_CONSUMABILI_VECCHI_GIORNI", DEFAULT_GIORNI_CONSUMABILI))


def giorni_soglia_contatori() -> int:
    return int(getattr(settings, "ASSETS_MFC_CONTATORI_VECCHI_GIORNI", DEFAULT_GIORNI_CONTATORI))


def _eta(quando, ora) -> int | None:
    if quando is None:
        return None
    return max(0, (ora - quando).days)


def pagine_per_mese(letture: list[dict]) -> list[dict]:
    """Pagine stampate nel mese = differenza fra letture cumulative consecutive.

    ``letture`` ordinate per mese crescente con a4_bn/a3_bn/a4_col/a3_col. Un contatore
    che scende (sostituzione scheda, azzeramento) non diventa un numero negativo ne'
    zero: il mese resta "non calcolabile" (None). Un mese mancante interrompe la serie.
    """
    out = []
    for prev, cur in zip(letture, letture[1:]):
        mesi = (cur["mese"].year - prev["mese"].year) * 12 + cur["mese"].month - prev["mese"].month
        bn = (cur["a4_bn"] + cur["a3_bn"]) - (prev["a4_bn"] + prev["a3_bn"])
        col = (cur["a4_col"] + cur["a3_col"]) - (prev["a4_col"] + prev["a3_col"])
        valido = mesi == 1 and bn >= 0 and col >= 0
        # La lettura del mese M fotografa i contatori al giorno 1: la differenza con
        # il mese precedente sono le pagine del mese M-1.
        out.append({
            "mese": prev["mese"],
            "bn": bn if valido else None,
            "col": col if valido else None,
            "totale": bn + col if valido else None,
        })
    return out


def trend(serie: list[dict]) -> dict | None:
    """Media ultimi 3 mesi calcolabili contro i 3 precedenti: su/giu'/stabile (+-10%)."""
    valori = [m["totale"] for m in serie if m["totale"] is not None]
    if len(valori) < 6:
        return None
    recenti, precedenti = sum(valori[-3:]) / 3, sum(valori[-6:-3]) / 3
    if precedenti == 0:
        return None
    delta = round((recenti - precedenti) / precedenti * 100)
    direzione = "su" if delta > 10 else "giu" if delta < -10 else "stabile"
    return {"media_recente": round(recenti), "media_precedente": round(precedenti), "delta_pct": delta,
            "delta_abs": abs(delta), "direzione": direzione}


def statistiche_mfc(macchine: list[dict], ora=None) -> dict[int, dict]:
    """``macchine``: righe con almeno ``id``, ``snmp_stato``, ``snmp_ultimo_controllo``,
    ``snmp_ultimo_errore``. Ritorna ``{macchina_id: {...}}``; nessuna chiamata di rete."""
    from contatori.models import LetturaMensileContatori
    from contatori.services import SOGLIA_CONSUMABILE_PCT, stato_consumabili

    ora = ora or timezone.now()
    ids = [m["id"] for m in macchine]
    if not ids:
        return {}

    class _Ref:
        __slots__ = ("pk",)

        def __init__(self, pk):
            self.pk = pk

    consumabili = stato_consumabili([_Ref(pk) for pk in ids], ora=ora)

    oggi = timezone.localtime(ora).date()
    inizio = (oggi.replace(day=1) - timedelta(days=31 * (MESI_TREND + 1))).replace(day=1)
    per_macchina: dict[int, list[dict]] = defaultdict(list)
    for row in (
        LetturaMensileContatori.objects.filter(macchina_id__in=ids, mese__gte=inizio)
        .order_by("macchina_id", "mese")
        .values("macchina_id", "mese", "rilevata_il", "a4_bn", "a3_bn", "a4_col", "a3_col")
    ):
        per_macchina[row["macchina_id"]].append(row)

    soglia_cons, soglia_cont = giorni_soglia_consumabili(), giorni_soglia_contatori()
    out = {}
    for m in macchine:
        cons = consumabili.get(m["id"])
        letture = per_macchina.get(m["id"], [])
        serie = pagine_per_mese(letture)[-MESI_TREND:]
        ultima_mensile = letture[-1]["rilevata_il"] if letture else None
        eta_cons = _eta(cons["rilevata_il"], ora) if cons else None
        eta_cont = _eta(ultima_mensile, ora)
        massimo = max((s["totale"] or 0 for s in serie), default=0)
        for s in serie:
            s["altezza_pct"] = round((s["totale"] or 0) * 100 / massimo) if massimo else 0
        out[m["id"]] = {
            "consumabili": cons,
            "consumabili_eta_giorni": eta_cons,
            "consumabili_vecchi": eta_cons is not None and eta_cons > soglia_cons,
            "pagine_mesi": serie,
            "pagine_ultimo_mese": next((s for s in reversed(serie) if s["totale"] is not None), None),
            "trend": trend(serie),
            "contatori_eta_giorni": eta_cont,
            "contatori_vecchi": eta_cont is not None and eta_cont > soglia_cont,
            "soglia_consumabili_giorni": soglia_cons,
            "soglia_contatori_giorni": soglia_cont,
            "soglia_pct": SOGLIA_CONSUMABILE_PCT,
            "errore_snmp": (m.get("snmp_ultimo_errore") or "")[:200] if m.get("snmp_stato") == "ERROR" else "",
        }
    return out


def candidati_collegamento(asset, ips: list[str]) -> list[dict]:
    """MFC non collegate che corrispondono per matricola o IP a questo asset (max 5).

    Solo una proposta da confermare: il collegamento vero passa dalla riconciliazione
    IT, che ricalcola l'abbinamento univoco e verifica il permesso.
    """
    from django.db.models import Q

    from contatori.models import Macchina

    filtro = Q()
    serial = (asset.serial_number or "").strip()
    if serial:
        filtro |= Q(matricola__iexact=serial)
    ips = [ip for ip in ips if ip][:10]
    if ips:
        filtro |= Q(host__in=ips)
    if not filtro:
        return []
    return list(
        Macchina.objects.filter(filtro, asset__isnull=True).order_by("reparto", "pk")
        .values("id", "reparto", "matricola", "host", "modello")[:5]
    )
