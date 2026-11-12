"""Storico delle patch WatchGuard chiuse: cosa è stato installato, su quale PC, quali CVE ha corretto.

Una ``WatchGuardPatch`` si chiude (``presente=False`` + ``chiusa_il``) quando WatchGuard non la segnala
più. Il motivo non sempre è noto, e la pagina lo dice riga per riga:

- ``confermata``: un task di installazione WatchGuard ha registrato «Installata» o «Era già installata»;
- ``pc_uscito``: il PC non è più fra i dispositivi WatchGuard (la patch è sparita col PC);
- ``non_segnalata``: WatchGuard non la segnala più, senza un esito di installazione (installata da
  Windows Update o dall'utente, oppure sostituita da una patch più recente).

Il contatore «patch chiuse» della pagina Patch e protezione usa ``conta_chiuse``: stessa metrica, stessa funzione.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from security.models import SecurityCveRecord, WatchGuardDispositivo, WatchGuardPatch

PERIODI = {"30": 30, "90": 90, "365": 365, "tutto": None}
PERIODI_LABEL = {"30": "Ultimi 30 giorni", "90": "Ultimi 90 giorni", "365": "Ultimo anno", "tutto": "Tutto lo storico"}
PERIODO_DEFAULT = "90"

ESITI_CONFERMA = (1, 5)  # «Installata», «Era già installata»

MOTIVI = {
    "confermata": "Installata (esito del task WatchGuard)",
    "non_segnalata": "Non più segnalata da WatchGuard",
    "pc_uscito": "PC non più in WatchGuard",
}
FILTRI_MOTIVO = {"": "Tutte", **MOTIVI}

RIGHE_MAX = 500


def _chiuse(giorni):
    qs = WatchGuardPatch.objects.filter(presente=False, chiusa_il__isnull=False)
    if giorni:
        qs = qs.filter(chiusa_il__gte=timezone.now() - timedelta(days=giorni))
    return qs


def conta_chiuse(giorni=30) -> int:
    return _chiuse(giorni).count()


def motivo(p: WatchGuardPatch, dispositivi_presenti: set[str]) -> str:
    if p.esito in ESITI_CONFERMA:
        return "confermata"
    if p.device_id not in dispositivi_presenti:
        return "pc_uscito"
    return "non_segnalata"


def installate(periodo=PERIODO_DEFAULT, motivo_filtro="", q="") -> dict:
    """Patch chiuse nel periodo (più recenti prima) con il motivo, le CVE corrette e il riepilogo."""
    periodo = periodo if periodo in PERIODI else PERIODO_DEFAULT
    motivo_filtro = motivo_filtro if motivo_filtro in FILTRI_MOTIVO else ""
    qs = _chiuse(PERIODI[periodo]).select_related("hub_asset").order_by("-chiusa_il", "host", "nome")
    testo = (q or "").strip()
    if testo:
        qs = qs.filter(Q(host__icontains=testo) | Q(host_display__icontains=testo) | Q(nome__icontains=testo)
                       | Q(programma__icontains=testo) | Q(cve__icontains=testo.upper()))
    presenti = set(WatchGuardDispositivo.objects.filter(presente=True).values_list("device_id", flat=True))

    righe = []
    for p in qs:
        m = motivo(p, presenti)
        if motivo_filtro and m != motivo_filtro:
            continue
        righe.append({"p": p, "motivo": m, "motivo_label": MOTIVI[m], "cve": p.cve_lista})

    tutte_cve = {c for r in righe for c in r["cve"]}
    kev = set(SecurityCveRecord.objects.filter(kev=True, cve_id__in=tutte_cve).values_list("cve_id", flat=True)) if tutte_cve else set()
    for r in righe:
        r["kev"] = [c for c in r["cve"] if c in kev]

    per_motivo = {k: 0 for k in MOTIVI}
    for r in righe:
        per_motivo[r["motivo"]] += 1
    return {
        "periodo": periodo, "periodi": list(PERIODI_LABEL.items()),
        "motivo": motivo_filtro, "motivi_scelte": list(FILTRI_MOTIVO.items()), "q": testo,
        "righe": righe, "righe_mostrate": righe[:RIGHE_MAX], "righe_max": RIGHE_MAX,
        "kpi": {
            "patch": len(righe),
            "pc": len({r["p"].host for r in righe}),
            "cve": len(tutte_cve),
            "kev": len(kev),
            "critiche": sum(1 for r in righe if r["p"].criticita == 201),
            **per_motivo,
        },
    }
