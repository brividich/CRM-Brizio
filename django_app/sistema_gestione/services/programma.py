"""Programma basato sul rischio: ciclo triennale, frequenza raccomandata, calendario, impostazioni."""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from django.db.models import Q

from ..models import Audit, CellaProgramma, CicloAudit, ProgrammaAudit, Processo

CAMPI_NORMA = [
    ("en9100", "punti_9100", "EN 9100"), ("iso45001", "punti_45001", "ISO 45001"),
    ("iso14001", "punti_14001", "ISO 14001"), ("iso27001", "punti_27001", "ISO/IEC 27001"),
    ("pdr125", "punti_pdr125", "UNI/PdR 125"),
]

# Impostazioni del modulo (SiteConfig): chiave -> (etichetta, default, tipo)
IMPOSTAZIONI = {
    "sistema_gestione.audit_chiusura_richiede_car_approvate": (
        "Chiusura dell'audit solo con il piano azioni approvato per ogni NC", "1", "bool"),
    "sistema_gestione.audit_deroga_imparzialita_ammessa": (
        "Ammetti la deroga motivata all'indipendenza dell'auditor, approvata dall'RDD", "0", "bool"),
    "sistema_gestione.car_escalation_giorni": (
        "Giorni di ritardo di una CAR prima dell'escalation a RSGI", "15", "int"),
    "sistema_gestione.audit_email_rsgi": (
        "Email RSGI per escalation (separate da virgola)", "", "text"),
}


def impostazione(chiave: str) -> str:
    from core.models import SiteConfig

    return SiteConfig.get(chiave, IMPOSTAZIONI[chiave][1]) or IMPOSTAZIONI[chiave][1]


def impostazione_attiva(chiave: str) -> bool:
    return impostazione(chiave).strip().lower() not in {"0", "false", "no", ""}


def deroga_imparzialita_ammessa() -> bool:
    return impostazione_attiva("sistema_gestione.audit_deroga_imparzialita_ammessa")


def _punti(valore: str) -> set[str]:
    return {v.strip() for v in re.split(r"[,;\n]", valore or "") if v.strip()}


def frequenza_raccomandata(processo: Processo, *, nc: int, ofi: int, non_efficaci: int) -> tuple[int, list[str]]:
    """Proposta di frequenza (mesi) dal rischio. Non supera mai la frequenza della scheda né i
    12 mesi di MT CN 12: il rischio può solo avvicinare la verifica, non allontanarla."""
    mesi = min(int(processo.frequenza_mesi or 12), 12)
    motivi = []
    if processo.criticita == 3 and mesi > 6:
        mesi, motivi = 6, motivi + ["criticità alta: verifica almeno semestrale"]
    if nc and mesi > 6:
        mesi, motivi = 6, motivi + [f"{nc} NC negli ultimi 24 mesi: verifica almeno semestrale"]
    if non_efficaci and mesi > 6:
        mesi, motivi = 6, motivi + ["azioni non efficaci: verifica almeno semestrale"]
    if ofi >= 3 and mesi > 9:
        mesi, motivi = 9, motivi + [f"{ofi} OFI negli ultimi 24 mesi"]
    return mesi, motivi


def copertura_ciclo(ciclo: CicloAudit) -> dict:
    """Per ogni processo attivo: anni con audit eseguito o programmato e clausole del catalogo
    mai programmate nel ciclo. È l'evidenza da mostrare all'ente di certificazione."""
    anni = ciclo.anni
    programmi = {}
    for p in ProgrammaAudit.objects.filter(anno__in=anni).exclude(stato=ProgrammaAudit.STATO_SUPERATO).order_by("anno", "-revisione"):
        programmi.setdefault(p.anno, p)
    celle = list(CellaProgramma.objects.filter(riga__programma__in=programmi.values()).select_related("riga", "riga__programma"))
    chiusi = Audit.objects.filter(stato=Audit.STATO_CHIUSO, data_inizio__year__in=anni).prefetch_related("processi_catalogo")
    eseguiti = {(a.data_inizio.year, p.pk) for a in chiusi for p in a.processi_catalogo.all()}
    righe = []
    for processo in Processo.objects.filter(attivo=True).order_by("codice"):
        proprie = [c for c in celle if c.riga.processo_id == processo.pk]
        per_anno = []
        for anno in anni:
            if (anno, processo.pk) in eseguiti:
                per_anno.append({"anno": anno, "stato": "eseguito"})
            elif any(c.riga.programma.anno == anno for c in proprie):
                per_anno.append({"anno": anno, "stato": "programmato"})
            else:
                per_anno.append({"anno": anno, "stato": ""})
        scoperte = []
        for _flag, campo, label in CAMPI_NORMA:
            richieste = _punti(getattr(processo, campo, ""))
            coperte = set().union(*[_punti(getattr(c.riga, campo, "")) for c in proprie]) if proprie else set()
            scoperte += [f"{label} {v}" for v in sorted(richieste - coperte)]
        righe.append({
            "processo": processo, "anni": per_anno, "clausole_scoperte": scoperte,
            "mai_verificato": not any(a["stato"] == "eseguito" for a in per_anno),
        })
    return {
        "anni": anni, "righe": righe, "programmi": [{"anno": a, "programma": programmi.get(a)} for a in anni],
        "processi_scoperti": sum(1 for r in righe if not any(a["stato"] for a in r["anni"])),
        "clausole_scoperte": sum(len(r["clausole_scoperte"]) for r in righe),
    }


def calendario_mese(anno: int, mese: int) -> dict:
    """Settimane del mese con audit (per giorno) e verifiche programmate senza data (per mese)."""
    primo = date(anno, mese, 1)
    ultimo = date(anno, mese, calendar.monthrange(anno, mese)[1])
    audit = list(Audit.objects.filter(
        Q(data_inizio__lte=ultimo) & (Q(data_fine__gte=primo) | Q(data_fine__isnull=True, data_inizio__gte=primo)),
    ).exclude(stato=Audit.STATO_ANNULLATO).select_related("lead_auditor__user").order_by("data_inizio"))
    per_giorno: dict[date, list] = {}
    for a in audit:
        giorno = max(a.data_inizio, primo)
        while giorno <= min(a.data_fine or a.data_inizio, ultimo):
            per_giorno.setdefault(giorno, []).append(a)
            giorno += timedelta(days=1)
    programmi = [p for p in ProgrammaAudit.objects.filter(anno=anno).exclude(stato=ProgrammaAudit.STATO_SUPERATO).order_by("-revisione")[:1]]
    da_pianificare = list(CellaProgramma.objects.filter(
        riga__programma__in=programmi, mese=mese, audit__isnull=True,
    ).select_related("riga"))
    settimane = []
    for settimana in calendar.Calendar(firstweekday=0).monthdatescalendar(anno, mese):
        settimane.append([{"giorno": g, "nel_mese": g.month == mese, "audit": per_giorno.get(g, [])} for g in settimana])
    precedente = (primo - timedelta(days=1)).replace(day=1)
    successivo = ultimo + timedelta(days=1)
    return {"anno": anno, "mese": mese, "primo": primo, "settimane": settimane, "da_pianificare": da_pianificare,
            "precedente": precedente, "successivo": successivo}
