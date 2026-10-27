"""Pacchetto mensile di evidenze ISO/IEC 27001 del SOC (controlli 9.1 e 9.3).

Il giorno 1 di ogni mese alle 06:30 (schedule ``security_pacchetto_iso``, lettura ``pacchetto_iso``) e con
«Genera ora» nella pagina Conformità ISO 27001 si produce il PDF «Evidenze SOC – ISO/IEC 27001 – <periodo>»:
copertina, tabella di sintesi per controllo, una sezione per controllo con i numeri, e in allegato le
vulnerabilità corrette nel periodo, le esposizioni oltre il termine e gli incidenti con lo stato del riesame.

Il file va nello storage privato (``SecurityPacchettoIso``), l'impronta SHA-256 nell'audit sigillato del
portale (``core.audit.log_action``) e, se acceso in Avvisi e automatismi, una copia nella cartella SharePoint
dell'audit (stesso meccanismo di ``registro_log.archivio.copia_mancanti``). Le parti che dipendono da servizi
di altri rami (``cve_sla``) mancano con «dato non disponibile», senza fermare il pacchetto.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date

from django.core.files.base import ContentFile
from django.utils import timezone

from security.services import iso27001

logger = logging.getLogger(__name__)

CARTELLA_SHAREPOINT = "soc-iso27001"
COME_LABEL = {"aggiornato": "Programma aggiornato", "rimosso": "Programma disinstallato"}


def _dt(value, fmt="%d/%m/%Y %H:%M"):
    if not value:
        return "—"
    if hasattr(value, "tzinfo") and timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime(fmt)


def correzioni(dal: date, al: date) -> list[dict]:
    """CVE corrette nel periodo: PC, versione prima e dopo, come lo sappiamo, date (da ``SecurityCveRisoluzione``)."""
    from security.models import SecurityCveRisoluzione

    da, a = iso27001._istanti(dal, al)
    out = []
    for r in (SecurityCveRisoluzione.objects.filter(risolta_il__range=(da, a), come__in=SecurityCveRisoluzione.CORREZIONI)
              .select_related("cve").order_by("risolta_il", "cve__cve_id", "host")):
        giorni = round((r.risolta_il - r.aperta_dal).total_seconds() / 86400) if r.aperta_dal else None
        out.append({
            "cve": r.cve.cve_id, "cvss": r.cve.cvss, "kev": r.cve.kev, "host": r.host_display or r.host, "software": r.software or r.chiave,
            "versione_prima": r.versione_prima or "—", "versione_dopo": r.versione_dopo or ("—" if r.come == "aggiornato" else "disinstallato"),
            "evidenza": f"{COME_LABEL.get(r.come, r.come)} (inventario software del PC)",
            "aperta_dal": _dt(r.aperta_dal, "%d/%m/%Y"), "risolta_il": _dt(r.risolta_il, "%d/%m/%Y"), "giorni": giorni,
        })
    return out


def esposizioni_scadute(dal: date, al: date) -> list[dict] | None:
    """Esposizioni oltre il termine (da ``cve_sla``); ``None`` se il servizio non c'è."""
    m = iso27001._modulo("cve_sla")
    if m is None:
        return None
    try:
        return list(m.riepilogo(dal, al).get("aperte_scadute") or [])
    except Exception:  # noqa: BLE001
        logger.exception("cve_sla.riepilogo non riuscito nel pacchetto ISO")
        return None


def incidenti(dal: date, al: date) -> list[dict]:
    """Incidenti rilevati o chiusi nel periodo, con lo stato delle lezioni apprese."""
    from django.db.models import Q

    from security.models import SecurityIncident

    da, a = iso27001._istanti(dal, al)
    qs = SecurityIncident.objects.filter(Q(detected_at__range=(da, a)) | Q(resolved_at__range=(da, a))).order_by("detected_at")
    out = []
    for i in qs:
        chiuso = i.status in (SecurityIncident.STATUS_RESOLVED, SecurityIncident.STATUS_CLOSED)
        if i.lessons_learned.strip():
            riesame = "fatto"
        elif chiuso:
            riesame = "mancante"
        else:
            riesame = "incidente ancora aperto"
        out.append({
            "codice": i.code or f"#{i.pk}", "titolo": i.title, "categoria": i.get_category_display(), "stato": i.get_status_display(),
            "rilevato_il": _dt(i.detected_at), "risolto_il": _dt(i.resolved_at), "nis2": "sì" if i.is_significant else "no",
            "dati_personali": "sì" if i.personal_data_breach else "no", "riesame": riesame,
            "lezioni": (i.lessons_learned.strip()[:300] + ("…" if len(i.lessons_learned.strip()) > 300 else "")) if i.lessons_learned.strip() else "",
        })
    return out


def dati(dal: date, al: date) -> dict:
    """Tutto ciò che va nel PDF: esito dei controlli e allegati."""
    return {
        "dal": dal, "al": al, "etichetta": iso27001.etichetta_mese(dal, al), "generato_il": timezone.now(),
        "valutazione": iso27001.valuta(dal, al), "correzioni": correzioni(dal, al),
        "esposizioni_scadute": esposizioni_scadute(dal, al), "incidenti": incidenti(dal, al),
    }


def _copia_sharepoint(pacchetto, contenuto: bytes) -> str:
    from security.services import soc_settings

    if not soc_settings.value("iso.pacchetto.sharepoint"):
        return ""
    try:
        from core import sharepoint_upload as sp

        drive, base = sp.destinazione()
        if not (drive and base):
            raise RuntimeError("Cartella SharePoint dell'audit non configurata (Centrale di comando › Audit).")
        try:
            sp.carica(pacchetto.nome_file, contenuto, drive_id=drive, cartella=f"{base}/{CARTELLA_SHAREPOINT}/{pacchetto.periodo_dal:%Y}")
        except sp.SharePointUploadError as exc:
            if "nameAlreadyExists" not in str(exc):
                raise
        return "Copiato su SharePoint."
    except Exception as exc:  # noqa: BLE001 - la copia non blocca l'archivio locale
        logger.warning("Pacchetto ISO %s: copia su SharePoint non riuscita: %s", pacchetto, exc)
        return f"Copia su SharePoint non riuscita: {exc}"[:500]


def genera(dal: date, al: date, *, utente=None, automatico: bool = False, request=None):
    """Genera il PDF del periodo, lo archivia con l'impronta e scrive l'audit. Ritorna il ``SecurityPacchettoIso``."""
    from core.audit import log_action
    from security.models import SecurityPacchettoIso
    from security.services.soc_pdf import render_pacchetto_iso_pdf

    d = dati(dal, al)
    contenuto = render_pacchetto_iso_pdf(d)
    impronta = hashlib.sha256(contenuto).hexdigest()
    v = d["valutazione"]
    pacchetto = SecurityPacchettoIso(
        periodo_dal=dal, periodo_al=al, sha256=impronta, automatico=automatico,
        generato_da=utente if getattr(utente, "pk", None) else None,
        riepilogo={
            "conteggi": v["conteggi"], "etichetta": v["etichetta"],
            "non_conformi": [f"{c['codice']} {c['titolo']}" for c in v["controlli"] if c["stato"] == iso27001.NON_CONFORME],
            "correzioni": len(d["correzioni"]), "incidenti": len(d["incidenti"]),
            "esposizioni_scadute": len(d["esposizioni_scadute"]) if d["esposizioni_scadute"] is not None else None,
            "byte": len(contenuto),
        },
    )
    pacchetto.file.save(pacchetto.nome_file, ContentFile(contenuto), save=False)
    pacchetto.copia_esito = _copia_sharepoint(pacchetto, contenuto)
    pacchetto.save()
    log_action(request, "pacchetto_iso_generato", "security", {
        "periodo_dal": dal.isoformat(), "periodo_al": al.isoformat(), "sha256": impronta, "byte": len(contenuto),
        "automatico": automatico, "conteggi": v["conteggi"], "copia": pacchetto.copia_esito,
    }, oggetto=pacchetto)
    return pacchetto


def giro_mensile():
    """La lettura ``pacchetto_iso``: il mese prima, una volta sola (un giro ripetuto non duplica il pacchetto)."""
    from security.models import SecurityPacchettoIso

    dal, al = iso27001.mese_precedente()
    if SecurityPacchettoIso.objects.filter(periodo_dal=dal, periodo_al=al, automatico=True).exists():
        return {"skipped": f"pacchetto di {iso27001.etichetta_mese(dal, al)} già generato"}
    p = genera(dal, al, automatico=True)
    c = p.riepilogo.get("conteggi") or {}
    out = {"periodo": p.riepilogo.get("etichetta"), "sha256": p.sha256, "non_conformi": c.get(iso27001.NON_CONFORME, 0),
           "attenzione": c.get(iso27001.ATTENZIONE, 0), "non_disponibili": c.get(iso27001.NON_DISPONIBILE, 0), "ok": c.get(iso27001.OK, 0)}
    if p.copia_esito:
        out["copia"] = p.copia_esito
        if "non riuscita" in p.copia_esito:
            out["errore"] = p.copia_esito
    return out
