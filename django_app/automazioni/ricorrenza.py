"""Passaggio «Ricorrenza» dei flussi pianificati, come in Power Automate.

Traduce il calendario di un ``ManagedFlow`` (ogni N minuti o cron a cinque campi) in
campi leggibili (frequenza, orario, giorni, giorno del mese) e viceversa. Quello che
non si riduce a questi campi resta «Personalizzato» con il cron a vista.
"""
from __future__ import annotations

# Ordine di Power Automate: da lunedì a domenica (cron: 1..6, 0).
GIORNI = [("1", "lun"), ("2", "mar"), ("3", "mer"), ("4", "gio"), ("5", "ven"), ("6", "sab"), ("0", "dom")]
TUTTI = {g for g, _ in GIORNI}
FREQUENZE = [
    ("minuti", "Ogni N minuti"),
    ("giorno", "Ogni giorno, nei giorni scelti"),
    ("mese", "Ogni mese, in un giorno"),
    ("personalizzato", "Personalizzato (cron)"),
]


def _espandi_giorni(campo: str) -> set[str] | None:
    """Giorni della settimana di un campo cron (``*``, ``1-5``, ``1,3,5``, ``7``=domenica); None se non leggibile."""
    if campo == "*":
        return set(TUTTI)
    giorni: set[str] = set()
    for pezzo in campo.split(","):
        if "-" in pezzo:
            a, _, b = pezzo.partition("-")
            if not (a.isdigit() and b.isdigit()) or int(a) > int(b) or int(b) > 7:
                return None
            giorni.update(str(int(x) % 7) for x in range(int(a), int(b) + 1))
        elif pezzo.isdigit() and int(pezzo) <= 7:
            giorni.add(str(int(pezzo) % 7))
        else:
            return None
    return giorni


def _compatta_giorni(giorni: set[str]) -> str:
    if giorni >= TUTTI:
        return "*"
    return ",".join(g for g, _ in sorted(GIORNI, key=lambda x: int(x[0])) if g in giorni)


def da_flusso(schedule_type: str, minutes: int | None, cron: str) -> dict:
    """Campi del passaggio «Ricorrenza» per il calendario attuale."""
    r = {"frequenza": "personalizzato", "minuti": minutes or 60, "orario": "07:00",
         "giorni": set(TUTTI), "giorno_mese": 1, "cron": cron or ""}
    if schedule_type == "I":
        r["frequenza"] = "minuti"
        return r
    parts = str(cron or "").split()
    if len(parts) != 5 or not (parts[0].isdigit() and parts[1].isdigit()):
        return r
    m, h, dom, mon, dow = parts
    if int(m) > 59 or int(h) > 23:
        return r
    r["orario"] = f"{int(h):02d}:{int(m):02d}"
    if dom == "*" and mon == "*":
        giorni = _espandi_giorni(dow)
        if giorni:
            r.update(frequenza="giorno", giorni=giorni)
    elif dom.isdigit() and 1 <= int(dom) <= 31 and mon == "*" and dow == "*":
        r.update(frequenza="mese", giorno_mese=int(dom))
    return r


def a_flusso(dati) -> tuple[str, int, str]:
    """(schedule_type, minutes, cron) dai campi inviati. ValueError con un messaggio leggibile se non validi."""
    frequenza = (dati.get("frequenza") or "").strip()
    if frequenza == "minuti":
        try:
            minuti = int(dati.get("minuti") or 0)
        except ValueError:
            minuti = 0
        if not 1 <= minuti <= 10080:
            raise ValueError("Intervallo ammesso: da 1 a 10080 minuti.")
        return "I", minuti, ""
    if frequenza == "personalizzato":
        from croniter import croniter

        cron = " ".join((dati.get("cron") or "").split())
        if len(cron.split()) != 5 or not croniter.is_valid(cron):
            raise ValueError("Calendario personalizzato non valido: servono cinque campi (minuto ora giorno mese giorno-settimana).")
        return "C", 1, cron
    try:
        ora_s, minuto_s = (dati.get("orario") or "").strip().split(":")[:2]
        ora, minuto = int(ora_s), int(minuto_s)
    except ValueError:
        raise ValueError("Orario non valido: usa il formato HH:MM.")
    if not (0 <= ora <= 23 and 0 <= minuto <= 59):
        raise ValueError("Orario non valido: usa il formato HH:MM.")
    if frequenza == "giorno":
        giorni = {g for g in (dati.getlist("giorni") if hasattr(dati, "getlist") else dati.get("giorni") or []) if g in TUTTI}
        if not giorni:
            raise ValueError("Scegli almeno un giorno della settimana.")
        return "C", 1, f"{minuto} {ora} * * {_compatta_giorni(giorni)}"
    if frequenza == "mese":
        try:
            giorno = int(dati.get("giorno_mese") or 0)
        except ValueError:
            giorno = 0
        if not 1 <= giorno <= 31:
            raise ValueError("Giorno del mese: da 1 a 31.")
        return "C", 1, f"{minuto} {ora} {giorno} * *"
    raise ValueError("Frequenza non riconosciuta.")
