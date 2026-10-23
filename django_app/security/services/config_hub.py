"""Panoramica della configurazione del SOC (``/soc/admin/config/``): le sezioni divise per compito.

Ogni voce dice in una frase a cosa serve e il suo stato in parole («3 caselle attive · ultima lettura
alle 12:10»), invece di numeri «attivi/avvisi» uguali per tutte. In cima «Da sistemare»: solo le
cose concrete da fare, ognuna con il link alla pagina giusta. Ogni conteggio è isolato: se uno
fallisce la voce resta, senza stato.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

logger = logging.getLogger(__name__)


@dataclass
class Voce:
    rotta: str
    nome: str
    descrizione: str
    stato: str = ""
    tono: str = "idle"  # ok | warn | ko | idle
    url: str = ""


def _quando(dt):
    if not dt:
        return "mai"
    locale = timezone.localtime(dt)
    if locale.date() == timezone.localdate():
        return f"oggi alle {locale:%H:%M}"
    return date_format(locale, "d/m/Y")


def _plur(n, uno, molti):
    return f"{n} {uno if n == 1 else molti}"


def _sicuro(fn, voce, problemi):
    try:
        fn(voce, problemi)
    except Exception:  # noqa: BLE001 - un conteggio rotto non toglie la voce
        logger.exception("Panoramica configurazione: stato di %s non calcolato", voce.rotta)


# --- Stato delle singole voci -------------------------------------------------------------------

def _caselle(v, problemi):
    from security.models import SecurityMailboxIngestionRun, SecurityMailboxSource

    attive = list(SecurityMailboxSource.objects.filter(enabled=True).exclude(source_type="manual"))
    if not attive:
        v.stato, v.tono = "nessuna casella attiva", "ko"
        problemi.append(("Nessuna casella mail attiva: i report via mail (antivirus, firewall, backup) non arrivano.", v.url))
        return
    ultimo = SecurityMailboxIngestionRun.objects.filter(source__in=attive).order_by("-started_at").first()
    ko = [s for s in attive if (r := s.ingestion_runs.order_by("-started_at").first()) and r.status == "failed"]
    v.stato = f"{_plur(len(attive), 'casella attiva', 'caselle attive')} · ultima lettura {_quando(ultimo.started_at if ultimo else None)}"
    v.tono = "ko" if ko else "ok"
    if ko:
        problemi.append((f"{_plur(len(ko), 'casella mail', 'caselle mail')} con l'ultima lettura non riuscita: "
                         + ", ".join(s.name for s in ko[:3]), v.url))


def _letture(v, problemi):
    from security.services import letture

    c = letture.stato_pagina()["conteggi"]
    v.stato = f"{_plur(c['accese'], 'attiva', 'attive')} su {c['totale']}"
    if c["errori"]:
        v.stato += f" · {c['errori']} da sistemare"
        v.tono = "ko"
        problemi.append((f"{_plur(c['errori'], 'lettura automatica', 'letture automatiche')} con un errore o da configurare.", v.url))
    else:
        v.tono = "ok" if c["accese"] else "idle"


def _sorgenti(v, problemi):
    from security.models import SecurityParserConfig, SecuritySourceConfig
    from security.services import metriche

    sorgenti = SecuritySourceConfig.objects.filter(enabled=True).count()
    parser = SecurityParserConfig.objects.filter(enabled=True).count()
    mute = metriche.sorgenti_mute().value
    v.stato = f"{_plur(sorgenti, 'sorgente', 'sorgenti')} · {_plur(parser, 'parser attivo', 'parser attivi')}"
    if mute:
        v.stato += f" · {mute} in ritardo"
        problemi.append((f"{_plur(mute, 'sorgente non manda', 'sorgenti non mandano')} report nei tempi attesi.",
                         reverse("security:admin_mailbox_sources_list")))
    v.tono = "warn" if mute else ("ok" if sorgenti else "idle")


def _inventario(v, problemi):
    from security.models import SoftwareInstallation, SoftwareInventoryImport

    n = SoftwareInstallation.objects.filter(still_detected=True).count()
    ultimo = SoftwareInventoryImport.objects.order_by("-created_at").first()
    v.stato = f"{_plur(n, 'programma installato', 'programmi installati')} · ultimo import {_quando(ultimo.created_at if ultimo else None)}"
    v.tono = "ok" if n else "idle"


def _cpe(v, problemi):
    from security.models import SoftwareCpeMapping

    confermati = SoftwareCpeMapping.objects.filter(confirmed=True).count()
    da_fare = SoftwareCpeMapping.objects.filter(confirmed=False, not_applicable=False).count()
    v.stato = f"{_plur(confermati, 'software collegato', 'software collegati')}"
    if da_fare:
        v.stato += f" · {da_fare} da confermare"
        problemi.append((f"{_plur(da_fare, 'software da collegare', 'software da collegare')} alle CVE (CPE da confermare): "
                         "finché non sono collegati il SOC non sa se sono vulnerabili.", v.url))
    v.tono = "warn" if da_fare else ("ok" if confermati else "idle")


def _regole(v, problemi):
    from security.models import SecurityAlertRuleConfig

    attive = SecurityAlertRuleConfig.objects.filter(enabled=True).count()
    totale = SecurityAlertRuleConfig.objects.count()
    v.stato, v.tono = f"{attive} attive su {totale}", ("ok" if attive else "warn")


def _soppressioni(v, problemi):
    from security.models import SecurityAlertSuppressionRule

    attive = SecurityAlertSuppressionRule.objects.filter(is_active=True).count()
    v.stato, v.tono = _plur(attive, "regola attiva", "regole attive"), "ok" if attive else "idle"


def _rientro(v, problemi):
    from security.services.auto_resolution import registry_rows

    righe = list(registry_rows())
    attivi = sum(1 for r in righe if r["enabled"])
    v.stato, v.tono = f"{attivi} attivi su {len(righe)}", "ok" if attivi else "idle"


def _avvisi(v, problemi):
    from security.services import soc_settings

    sezioni = soc_settings.form_sections()
    accese = sum(1 for s in sezioni if s["active"])
    v.stato, v.tono = f"{accese} gruppi accesi su {len(sezioni)}", "ok" if accese else "idle"


def _canali(v, problemi):
    from security.models import SecurityNotificationChannel

    attivi = SecurityNotificationChannel.objects.filter(enabled=True).count()
    if not attivi:
        v.stato, v.tono = "nessun canale attivo", "ko"
        problemi.append(("Nessun canale di notifica attivo: avvisi e report automatici non partono verso nessuno.", v.url))
        return
    v.stato, v.tono = _plur(attivi, "canale attivo", "canali attivi"), "ok"


def _ticket(v, problemi):
    from security.models import SecurityTicketConfig

    n = SecurityTicketConfig.objects.count()
    v.stato, v.tono = ("configurato" if n else "non configurato"), ("ok" if n else "idle")


def _backup(v, problemi):
    from security.models import BackupExpectedJobConfig
    from security.services.backup_monitoring import missing_backup_candidates

    attesi = BackupExpectedJobConfig.objects.filter(enabled=True).count()
    nuovi = len(missing_backup_candidates())
    v.stato = _plur(attesi, "job atteso", "job attesi")
    if nuovi:
        v.stato += f" · {nuovi} visti ma non configurati"
        problemi.append((f"{_plur(nuovi, 'job di backup visto', 'job di backup visti')} nei report ma non configurati: "
                         "senza configurazione il SOC non avvisa se smettono di girare.", v.url))
    v.tono = "warn" if nuovi else ("ok" if attesi else "idle")


def _audit(v, problemi):
    from security.models import SecurityConfigurationAuditLog

    ultima = SecurityConfigurationAuditLog.objects.select_related("actor").order_by("-created_at").first()
    v.stato = f"ultima modifica {_quando(ultima.created_at)}" + (f" ({ultima.actor})" if ultima and ultima.actor else "") if ultima else "nessuna modifica"


SEZIONI = (
    ("dati", "Da dove arrivano i dati", "Le fonti che il SOC legge e come le interpreta.", (
        ("admin_mailbox_sources_list", "Caselle mail", "Le caselle che ricevono i report di antivirus, firewall e backup.", _caselle),
        ("letture", "Letture automatiche", "WatchGuard, Defender, Entra, Intune, CVE, switch: ultimo giro ed «Esegui ora».", _letture),
        ("admin_config_sources", "Sorgenti e parser", "Come si riconosce da dove arriva una mail e chi la legge.", _sorgenti),
        ("inventory", "Inventario software", "Programmi installati sui PC (import e letture automatiche).", _inventario),
        ("software_mapping", "Software e CVE (CPE)", "Collegare i programmi dell'inventario alle CVE.", _cpe),
    )),
    ("alert", "Cosa diventa un alert", "Le regole che decidono quando un evento apre un alert e quando si chiude.", (
        ("admin_config_alert_rules", "Regole alert", "Quali eventi aprono un alert e con che gravità.", _regole),
        ("suppressions", "Soppressioni", "Eventi noti che non devono aprire alert (anche quelle imparate).", _soppressioni),
        ("automation", "Automatismi di rientro", "Alert che si chiudono da soli quando il problema rientra.", _rientro),
        ("admin_config_backups", "Backup attesi", "Quali job di backup devono girare e ogni quanto.", _backup),
    )),
    ("avvisi", "Chi viene avvisato", "Avvisi automatici, report programmato, canali e ticket.", (
        ("soc_settings", "Avvisi e automatismi", "Scadenze incidenti, backup, report periodico, CVE, Defender, Entra, WatchGuard.", _avvisi),
        ("admin_config_notifications", "Canali di notifica", "Mail e Teams verso cui partono avvisi e report.", _canali),
        ("admin_config_ticketing", "Ticket", "Come nascono i ticket di rimedio.", _ticket),
    )),
    ("controllo", "Controllo e manutenzione", "Per verificare che tutto giri e per le modifiche tecniche.", (
        ("admin_diagnostics", "Diagnostica", "Controlla configurazione, sorgenti e lavori in background.", None),
        ("admin_autoconfig", "Autoconfigurazione", "Crea quello che manca e applica le correzioni suggerite.", None),
        ("pipeline", "Elaborazione", "Mail e file in coda di lettura e il loro esito.", None),
        ("admin_config_audit", "Registro modifiche", "Chi ha cambiato cosa nella configurazione.", _audit),
        ("admin_config_general", "Impostazioni tecniche", "Tutte le chiavi di configurazione, per casi particolari.", None),
    )),
)


def panoramica() -> dict:
    sezioni, problemi = [], []
    for codice, titolo, intro, voci in SEZIONI:
        righe = []
        for rotta, nome, descrizione, stato in voci:
            voce = Voce(rotta, nome, descrizione, url=reverse(f"security:{rotta}"))
            if stato:
                _sicuro(stato, voce, problemi)
            righe.append(voce)
        sezioni.append({"codice": codice, "titolo": titolo, "intro": intro, "voci": righe})
    return {"sezioni": sezioni, "problemi": problemi}


# Percorso «Configurazione › …» nelle pagine aperte dalla panoramica.
NOMI = {rotta: nome for _c, _t, _i, voci in SEZIONI for rotta, nome, _d, _s in voci}
NOMI.update({
    "admin_mailbox_source_detail": "Caselle mail", "admin_config_parsers": "Sorgenti e parser",
    "inventory_map": "Inventario software", "admin_config_suppressions": "Soppressioni",
    "admin_docs": "Documentazione", "admin_addons": "Moduli", "admin_addon_detail": "Moduli",
})
