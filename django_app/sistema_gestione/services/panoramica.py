"""«Da fare adesso» della pagina iniziale: audit e certificazioni in un solo elenco.

Non ricalcola niente di suo: usa le regole già in uso nelle pagine del modulo
(``audit_esterni.scadenze``, ``priorita_processi``, ``copertura_qualifiche``), così i
numeri coincidono con quelli che si trovano aprendo la voce.
"""
from __future__ import annotations

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from ..models import (
    Audit,
    AuditEsterno,
    Auditor,
    AzioneCorrettivaAudit,
    Certificazione,
    Processo,
    ProgrammaAudit,
)
from . import audit_automation
from .audit_esterni import scadenze
from .qualifiche import copertura_qualifiche

ALTA, MEDIA, BASSA = 0, 1, 2
TONI = {ALTA: "danger", MEDIA: "warn", BASSA: ""}
GIORNI_VICINI = 30
GIORNI_AUDITOR = 60
GIORNI_RIESAME = 60


def _voce(priorita: int, testo: str, url: str, azione: str, data=None, dettaglio: str = "") -> dict:
    return {"priorita": priorita, "tono": TONI[priorita], "testo": testo, "url": url, "azione": azione,
            "data": data, "dettaglio": dettaglio}


def _certificazioni(oggi) -> list[dict]:
    voci = []
    dati = scadenze(oggi, giorni_sorveglianza=GIORNI_VICINI)
    for c in dati["certificati"]:
        url = reverse("sistema_gestione:esterni_certificazione_scheda", args=[c.pk])
        if c.stato == "scaduta":
            voci.append(_voce(ALTA, f"Certificato {c.nome_breve} scaduto", url, "Apri", c.scade_il, c.ente))
        else:
            voci.append(_voce(MEDIA, f"Certificato {c.nome_breve} in scadenza", url, "Apri", c.scade_il, c.ente))
    for c in dati["sorveglianze"]:
        url = reverse("sistema_gestione:esterni_certificazione_scheda", args=[c.pk])
        if c.sorveglianza_superata:
            voci.append(_voce(MEDIA, f"Sorveglianza {c.nome_breve}: data superata, registra l'audit o aggiornala",
                              url, "Apri", c.prossima_sorveglianza, c.ente))
        else:
            voci.append(_voce(BASSA, f"Sorveglianza {c.nome_breve} in arrivo", url, "Apri",
                              c.prossima_sorveglianza, c.ente))
    for a in dati["risposte"]:
        url = reverse("sistema_gestione:esterni_audit", args=[a.pk])
        voci.append(_voce(ALTA if a.risposta_entro < oggi else MEDIA, f"Piano azioni da inviare a {a.ente}", url,
                          "Apri", a.risposta_entro, a.get_tipo_display()))
    for a in AuditEsterno.objects.filter(stato=AuditEsterno.STATO_PIANIFICATO, data_inizio__gte=oggi,
                                         data_inizio__lte=oggi + timedelta(days=GIORNI_VICINI)):
        url = reverse("sistema_gestione:esterni_audit", args=[a.pk])
        voci.append(_voce(BASSA, f"{a.get_tipo_display()}: {a.ente}", url, "Prepara", a.data_inizio))
    senza_copia = [c for c in Certificazione.objects.filter(attiva=True).prefetch_related("documenti")
                   if c.documento_corrente is None]
    if len(senza_copia) > 1:
        voci.append(_voce(BASSA, f"Manca la copia in PDF di {len(senza_copia)} certificati",
                          reverse("sistema_gestione:esterni_elenco"), "Carica", None,
                          ", ".join(c.nome_breve for c in senza_copia)))
    for c in senza_copia if len(senza_copia) == 1 else []:
        url = reverse("sistema_gestione:esterni_certificazione_scheda", args=[c.pk])
        voci.append(_voce(BASSA, f"Certificato {c.nome_breve}: manca la copia in PDF", url, "Carica", None, c.ente))
    from anagrafica.models import TipoQualifica

    tipi = TipoQualifica.objects.filter(certificazioni_sgi__attiva=True).distinct()
    for riga in copertura_qualifiche(tipi):
        if riga["scadute"]:
            voci.append(_voce(MEDIA, f"Qualifica «{riga['tipo'].nome}» collegata a un certificato: "
                                     f"scadute {riga['scadute']}",
                              reverse("anagrafica:qualifiche_scadenzario") + f"?tipo={riga['tipo'].pk}&stato=scaduta",
                              "Vedi"))
    return voci


def _audit_interni(oggi) -> list[dict]:
    voci = []
    if not ProgrammaAudit.objects.filter(anno=oggi.year, stato=ProgrammaAudit.STATO_APPROVATO).exists():
        voci.append(_voce(MEDIA, f"Programma audit {oggi.year} non approvato (MOD.034)",
                          reverse("sistema_gestione:audit_index"), "Apri"))
    for a in Audit.objects.filter(stato__in=(Audit.STATO_PIANIFICATO, Audit.STATO_PIANO_APPROVATO),
                                  data_inizio__isnull=False, data_inizio__lte=oggi + timedelta(days=GIORNI_VICINI)):
        url = reverse("sistema_gestione:audit_dettaglio", args=[a.pk])
        if a.data_inizio < oggi:
            voci.append(_voce(ALTA, f"Audit {a.numero} in ritardo", url, "Apri", a.data_inizio, a.get_stato_display()))
        else:
            voci.append(_voce(BASSA, f"Audit {a.numero} in arrivo", url, "Apri", a.data_inizio, a.get_stato_display()))
    da_verificare = [r for r in audit_automation.priorita_processi(Processo.objects.filter(attivo=True))
                     if r["mesi_dall_ultimo"] is None or r["oltre_frequenza"]]
    if da_verificare:
        voci.append(_voce(MEDIA, f"{len(da_verificare)} processi mai verificati o oltre la frequenza",
                          reverse("sistema_gestione:audit_priorita"), "Vedi le proposte"))
    car_scadute = [c for c in AzioneCorrettivaAudit.objects.filter(chiusa_il__isnull=True)
                   if c.scadenza_chiusura < oggi]
    if car_scadute:
        voci.append(_voce(ALTA, f"{len(car_scadute)} CAR oltre la scadenza di chiusura",
                          reverse("sistema_gestione:audit_cruscotto"), "Vedi"))
    for au in Auditor.objects.filter(attivo=True).select_related("user"):
        url = reverse("sistema_gestione:auditor_elenco")
        if au.qualifica_scaduta:
            voci.append(_voce(MEDIA, f"Qualifica dell'auditor {au.nome} scaduta", url, "Apri", au.qualifica_scadenza))
        elif au.qualifica_scadenza and au.qualifica_scadenza <= oggi + timedelta(days=GIORNI_AUDITOR):
            voci.append(_voce(BASSA, f"Qualifica dell'auditor {au.nome} in scadenza", url, "Apri",
                              au.qualifica_scadenza))
    return voci


def _riesame(oggi) -> list[dict]:
    from ..models import Riesame
    from .riesame import obiettivi_aperti, prossimo_riesame

    elenco = reverse("sistema_gestione:riesame_elenco")
    voci = []
    prossimo = prossimo_riesame()
    if prossimo is None:
        voci.append(_voce(MEDIA, "Nessun verbale di riesame approvato (MOD.062)", elenco, "Apri"))
    elif prossimo < oggi:
        voci.append(_voce(ALTA, "Riesame della direzione oltre l'anno", elenco, "Apri", prossimo))
    elif prossimo <= oggi + timedelta(days=GIORNI_RIESAME):
        voci.append(_voce(BASSA, "Riesame della direzione da pianificare", elenco, "Apri", prossimo))
    for r in Riesame.objects.filter(stato=Riesame.STATO_PROPOSTO):
        voci.append(_voce(MEDIA, f"Verbale di riesame {r.anno} da approvare",
                          reverse("sistema_gestione:riesame_dettaglio", args=[r.pk]), "Apri", r.data))
    for o in obiettivi_aperti():
        if o.scadenza and o.scadenza < oggi:
            url = reverse("sistema_gestione:riesame_dettaglio", args=[o.riesame_id]) + "#obiettivi"
            voci.append(_voce(MEDIA, f"Obiettivo del riesame oltre la scadenza: {o.descrizione[:70]}", url, "Apri", o.scadenza))
    return voci


def da_fare(oggi=None, *, audit: bool = True, riesame: bool = False) -> list[dict]:
    """Le cose da gestire, dalla più urgente; a parità di urgenza prima la data più vicina."""
    oggi = oggi or timezone.localdate()
    voci = _certificazioni(oggi) + _audit_interni(oggi) if audit else []
    if riesame:
        voci = voci + _riesame(oggi)
    return sorted(voci, key=lambda v: (v["priorita"], v["data"] is None, v["data"] or oggi, v["testo"]))


def colonne(voci: list[dict], oggi=None) -> list[dict]:
    """Le voci di ``da_fare`` divise per data, ciascuna in una sola colonna.

    Una voce ad alta priorità senza data (es. CAR oltre la scadenza) è comunque in ritardo.
    """
    oggi = oggi or timezone.localdate()
    limite = oggi + timedelta(days=GIORNI_VICINI)
    gruppi = {"ritardo": [], "vicino": [], "avanti": [], "senza": []}
    for v in voci:
        data = v["data"]
        if v["priorita"] == ALTA or (data and data < oggi):
            gruppi["ritardo"].append(v)
        elif data is None:
            gruppi["senza"].append(v)
        elif data <= limite:
            gruppi["vicino"].append(v)
        else:
            gruppi["avanti"].append(v)
    return [
        {"chiave": "ritardo", "titolo": "In ritardo", "voci": gruppi["ritardo"]},
        {"chiave": "vicino", "titolo": f"Entro {GIORNI_VICINI} giorni", "voci": gruppi["vicino"]},
        {"chiave": "avanti", "titolo": "Più avanti", "voci": gruppi["avanti"]},
        {"chiave": "senza", "titolo": "Senza data", "voci": gruppi["senza"]},
    ]

