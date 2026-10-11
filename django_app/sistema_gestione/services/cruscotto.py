"""Cruscotto degli audit interni ed estrazione dei rilievi (prompt 08, obiettivo E).

Query aggregate e mappe in memoria: il numero di query non cresce con audit o rilievi.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from ..models import Audit, AuditEsito, AuditVerificaEfficacia, AzioneCorrettivaAudit, CellaProgramma, Processo, ProgrammaAudit
from .programma import CAMPI_NORMA

RILIEVI = [AuditEsito.ESITO_NC, AuditEsito.ESITO_OFI, AuditEsito.ESITO_OSSERVAZIONE]


def _punti(valore: str) -> set[str]:
    return {v.strip() for v in re.split(r"[,;\n]", valore or "") if v.strip()}


def avanzamento_programma(anno: int, oggi: date | None = None) -> dict:
    oggi = oggi or timezone.localdate()
    programma = ProgrammaAudit.objects.filter(anno=anno, stato=ProgrammaAudit.STATO_APPROVATO).order_by("-revisione").first()
    if not programma:
        return {"programma": None, "pianificati": 0, "eseguiti": 0, "in_ritardo": 0, "da_fare": 0, "ritardi": []}
    celle = list(CellaProgramma.objects.filter(riga__programma=programma).select_related("riga", "audit"))
    eseguiti = [c for c in celle if c.audit_id and c.audit.stato == Audit.STATO_CHIUSO]
    ritardi = [c for c in celle if c not in eseguiti and (anno, c.mese) < (oggi.year, oggi.month)]
    return {"programma": programma, "pianificati": len(celle), "eseguiti": len(eseguiti), "in_ritardo": len(ritardi),
            "da_fare": len(celle) - len(eseguiti) - len(ritardi), "ritardi": ritardi}


def rilievi_anno(anno: int):
    return (AuditEsito.objects.filter(esito__in=RILIEVI, audit__data_inizio__year=anno)
            .exclude(audit__stato=Audit.STATO_ANNULLATO)
            .select_related("audit", "processo", "ofi", "ofi__car_procedurale", "responsabile_azione", "domanda__sezione", "sezione")
            .order_by("audit__data_inizio", "audit__numero", "pk"))


def _processo_label(esito) -> str:
    if esito.processo_id:
        return str(esito.processo)
    return esito.domanda_snapshot.get("processo") or (esito.audit.processi.splitlines()[0] if esito.audit.processi else "—")


def cruscotto(anno: int, oggi: date | None = None) -> dict:
    oggi = oggi or timezone.localdate()
    rilievi = list(rilievi_anno(anno))
    per_processo: dict[str, Counter] = defaultdict(Counter)
    per_clausola: Counter = Counter()
    per_mese: dict[int, Counter] = defaultdict(Counter)
    for e in rilievi:
        chiave = "NC_MAGGIORE" if e.esito == "NC" and e.gravita == "MAGGIORE" else "NC_MINORE" if e.esito == "NC" else e.esito
        per_processo[_processo_label(e)][chiave] += 1
        per_clausola[e.clausola_effettiva or "—"] += 1
        per_mese[e.audit.data_inizio.month][chiave] += 1
    chiuse = list(AzioneCorrettivaAudit.objects.filter(chiusa_il__isnull=False, chiusa_il__year=anno).only("data_richiesta", "chiusa_il"))
    giorni = [(timezone.localtime(c.chiusa_il).date() - c.data_richiesta).days for c in chiuse]
    ultime: dict[int, str] = {}
    for v in AuditVerificaEfficacia.objects.filter(data_verifica__year=anno).order_by("esito_id", "-registrato_il").values("esito_id", "risultato"):
        ultime.setdefault(v["esito_id"], v["risultato"])
    efficaci = sum(1 for r in ultime.values() if r == "EFFICACE")
    da_ricorrenti = (AuditEsito.objects.filter(esito__in=[AuditEsito.ESITO_NC, AuditEsito.ESITO_OFI], processo__isnull=False,
                                               audit__data_inizio__gte=oggi - timedelta(days=730))
                     .exclude(audit__stato=Audit.STATO_ANNULLATO)
                     .values("processo").annotate(audit_distinti=Count("audit", distinct=True), rilievi=Count("pk"))
                     .filter(audit_distinti__gte=2).order_by("-rilievi"))
    nomi = {p.pk: str(p) for p in Processo.objects.filter(pk__in=[r["processo"] for r in da_ricorrenti])}
    return {
        "anno": anno,
        "avanzamento": avanzamento_programma(anno, oggi),
        "totali": Counter(("NC_MAGGIORE" if e.esito == "NC" and e.gravita == "MAGGIORE" else "NC_MINORE" if e.esito == "NC" else e.esito) for e in rilievi),
        "per_processo": sorted(((k, dict(v), sum(v.values())) for k, v in per_processo.items()), key=lambda r: -r[2]),
        "per_clausola": per_clausola.most_common(15),
        "per_mese": [{"mese": m, "NC": per_mese[m]["NC_MAGGIORE"] + per_mese[m]["NC_MINORE"],
                      "OFI": per_mese[m]["OFI"], "OSS": per_mese[m]["OSS"]} for m in range(1, 13)],
        "car_chiuse": len(chiuse),
        "giorni_medi_chiusura": round(sum(giorni) / len(giorni)) if giorni else None,
        "efficacia": {"verificate": len(ultime), "efficaci": efficaci,
                      "percentuale": round(100 * efficaci / len(ultime)) if ultime else None},
        "ricorrenti": [{"processo": nomi.get(r["processo"], r["processo"]), "audit": r["audit_distinti"], "rilievi": r["rilievi"]} for r in da_ricorrenti],
        "copertura": copertura_clausole(anno),
    }


def copertura_clausole(anno: int) -> list[dict]:
    """Per norma: clausole richieste dal catalogo processi e clausole effettivamente verificate
    (esiti valutati, non N/A) negli audit chiusi dell'anno. Evidenza per l'ente di certificazione."""
    richieste: dict[str, set[str]] = defaultdict(set)
    for processo in Processo.objects.filter(attivo=True).only(*[c for _f, c, _l in CAMPI_NORMA]):
        for _flag, campo, label in CAMPI_NORMA:
            richieste[label] |= _punti(getattr(processo, campo, ""))
    verificate: dict[str, set[str]] = defaultdict(set)
    esiti = (AuditEsito.objects.filter(audit__stato=Audit.STATO_CHIUSO, audit__data_inizio__year=anno)
             .exclude(esito__in=["", AuditEsito.ESITO_NA]).select_related("audit", "domanda"))
    for e in esiti:
        punti = _punti(e.clausola_effettiva)
        for flag, _campo, label in CAMPI_NORMA:
            if getattr(e.audit, flag, False):
                verificate[label] |= punti
    out = []
    for _flag, _campo, label in CAMPI_NORMA:
        richiesto = richieste.get(label, set())
        if not richiesto:
            continue
        coperte = richiesto & verificate.get(label, set())
        out.append({"norma": label, "richieste": len(richiesto), "verificate": len(coperte),
                    "percentuale": round(100 * len(coperte) / len(richiesto)),
                    "mancanti": sorted(richiesto - coperte)})
    return out


def righe_rilievi(esiti) -> list[list]:
    righe = []
    for e in esiti:
        car = getattr(e.ofi, "car_procedurale", None) if e.ofi_id else None
        stato_car = ("Chiusa" if car.chiusa_il else "Approvata" if car.approvata_il else "Aperta") if car else ("—" if not e.ofi_id else "Da aprire")
        righe.append([
            e.audit.numero, e.audit.data_inizio, _processo_label(e), e.clausola_effettiva, e.esito_label,
            e.scostamento or e.evidenze, e.requisito_atteso,
            (e.responsabile_azione.get_full_name() or e.responsabile_azione.get_username()) if e.responsabile_azione_id else "",
            e.scadenza_azione, e.ofi.numero if e.ofi_id else "", stato_car,
        ])
    return righe


COLONNE_RILIEVI = ["Audit", "Data", "Processo", "Clausola", "Rilievo", "Scostamento / evidenza", "Requisito",
                   "Responsabile", "Scadenza", "MOD.174 n.", "CAR"]
