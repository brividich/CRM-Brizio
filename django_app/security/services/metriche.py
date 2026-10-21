"""Catalogo dei numeri del SOC: una definizione per ogni numero mostrato.

Regole (valgono per riquadri, contatori del menu, Panoramica ed elenchi):
1. ogni numero si calcola **solo** qui; le pagine non contano per conto loro;
2. ogni numero dichiara unità (PC, alert, segnalazioni...) e periodo («adesso» o «ultimi N giorni»);
3. il link porta a un elenco che mostra **esattamente** quelle righe (verificato dai test);
4. «adesso» = stato attuale, cosa c'è da fare; l'andamento di un periodo sta nei riquadri per area.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Count, Q
from django.urls import reverse

from security.models import SecurityAlert, Severity
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES

URGENT_SEVERITIES = (Severity.CRITICAL, Severity.HIGH)


@dataclass
class Metrica:
    key: str
    label: str          # etichetta breve accanto al numero
    unit: str           # cosa si conta
    periodo: str        # «adesso» o «ultimi N giorni»
    fonte: str          # da dove arriva il dato
    value: int
    url: str
    icon: str = "alert"
    tone: str = "success"  # success | warning | critical
    title: str = ""
    extra: dict = field(default_factory=dict)

    def as_item(self):
        return {"key": self.key, "label": self.label, "value": self.value, "tone": self.tone, "url": self.url,
                "title": self.title or f"{self.value} {self.unit} · {self.periodo} · fonte: {self.fonte}", "icon": self.icon}


# --- Segnalazioni -------------------------------------------------------------------------

def segnalazioni_urgenti():
    """Alert, ticket e incidenti aperti critici o alti, più gli incidenti con una notifica di legge scaduta o in scadenza."""
    from security.services import segnalazioni

    n = len(segnalazioni.elenco(urgenti=True))
    return Metrica("urgenti", "segnalazioni urgenti", "segnalazioni", "adesso", "alert, ticket e incidenti del SOC", n,
                   reverse("security:segnalazioni") + "?urgenti=1", icon="alert", tone="critical" if n else "success")


def segnalazioni_aperte():
    from security.services import segnalazioni

    n = sum(segnalazioni.conteggi().values())
    return Metrica("aperte", "segnalazioni aperte", "segnalazioni", "adesso", "alert, ticket e incidenti del SOC", n,
                   reverse("security:segnalazioni"), icon="bell", tone="warning" if n else "success")


def alert_urgenti():
    n = SecurityAlert.objects.filter(status__in=ACTIVE_ALERT_STATUSES, severity__in=URGENT_SEVERITIES).count()
    return Metrica("alert_urgenti", "alert critici e alti", "alert", "adesso", "regole del SOC sui report", n,
                   reverse("security:alerts_list") + "?status=active&severity=critical&severity=high", tone="critical" if n else "success")


def scadenze_legali():
    from security.services.incidents import urgent_incidents

    rows = urgent_incidents()
    overdue = sum(1 for r in rows if r["deadline"]["state"] == "overdue")
    return Metrica("nis2", "scadenze NIS2/GDPR", "incidenti", "adesso (scadute o entro 12 ore)", "registro incidenti", len(rows),
                   reverse("security:segnalazioni") + "?tipo=incident&scadenza=1", icon="clock",
                   tone="critical" if overdue else ("warning" if rows else "success"),
                   title=f"Notifiche scadute ({overdue}) o in scadenza entro 12 ore")


# --- Backup: sempre per PC ------------------------------------------------------------------

def pc_backup_ko_rows(days=7):
    from security.services.backup_center import FAIL, overview

    return [d for d in overview(days)["devices"] if d["stale"] or d["last_status"] == FAIL]


def pc_backup_ko(days=7):
    from security.services.backup_center import stale_days

    n = len(pc_backup_ko_rows(days))
    return Metrica("backup", "PC con backup ko", "PC", f"ultimi {days} giorni", "report di backup (Synology, Veeam)", n,
                   reverse("security:backup") + f"?giorni={days}&stato=ko#pc", icon="disk", tone="warning" if n else "success",
                   title=f"PC con l'ultimo backup fallito o senza un backup riuscito da oltre {stale_days()} giorni")


# --- Fonti dati -------------------------------------------------------------------------------

def sorgenti_mute():
    from security.services.source_heartbeat import source_status_rows

    n = sum(1 for r in source_status_rows() if r["state"] in ("high", "warning"))
    return Metrica("sources", "sorgenti in ritardo", "sorgenti", "adesso", "caselle mail dei report", n,
                   reverse("security:admin_mailbox_sources_list"), icon="signal", tone="warning" if n else "success",
                   title="Caselle che non mandano report nei tempi attesi")


# --- Vulnerabilità: CVE calcolate sull'inventario software dei nostri PC ---------------------

def cve_sui_pc():
    from security.models import SecurityCveImpact, SecurityCveRecord

    rows = SecurityCveRecord.objects.annotate(n=Count("impacts", filter=Q(impacts__outcome=SecurityCveImpact.IMPACTS))).filter(n__gt=0)
    total = rows.count()
    gravi = rows.filter(Q(kev=True) | Q(cvss__gte=9)).count()
    return Metrica("cve", "CVE sui nostri PC", "CVE", "inventario più recente", "inventario software + feed CVE", total,
                   reverse("security:vulnerabilities"), icon="alert", tone="critical" if gravi else ("warning" if total else "success"),
                   extra={"gravi": gravi})


def pc_esposti():
    from security.models import SecurityCveImpact

    n = SecurityCveImpact.objects.filter(outcome=SecurityCveImpact.IMPACTS).values("host").distinct().count()
    return Metrica("pc_esposti", "PC con CVE", "PC", "inventario più recente", "inventario software + feed CVE", n,
                   reverse("security:vulnerabilities") + "#pc", icon="monitor", tone="warning" if n else "success")


def copertura_cpe():
    """Quanti software presenti si possono controllare contro le CVE (collegati al CPE o dichiarati N/A)."""
    from security.models import SoftwareCpeMapping, SoftwareInstallation

    presenti = set(SoftwareInstallation.objects.filter(still_detected=True).values_list("vendor", "product").distinct())
    decisi = set(SoftwareCpeMapping.objects.filter(Q(confirmed=True) | Q(not_applicable=True)).values_list("vendor", "product"))
    coperti = len(presenti & decisi)
    totale = len(presenti)
    perc = round(100 * coperti / totale) if totale else 0
    return Metrica("copertura_cpe", "software controllabili", "software", "adesso", "Software e CPE", perc,
                   reverse("security:software_mapping") + "?stato=proposte", icon="shield",
                   tone="success" if perc >= 80 else ("warning" if perc >= 40 else "critical"),
                   extra={"coperti": coperti, "totale": totale, "da_decidere": totale - coperti})


# --- Gruppi usati dalle pagine ---------------------------------------------------------------

def barra_stato():
    """I quattro riquadri sotto il menu: lo stato di adesso, ogni numero con il suo elenco."""
    return [segnalazioni_urgenti(), scadenze_legali(), pc_backup_ko(), sorgenti_mute()]
