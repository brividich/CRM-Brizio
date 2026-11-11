"""Alert fermi: senza nuove occorrenze da «rumore.fermi.giorni» giorni → proposta di chiusura da confermare.

Non chiude niente: crea una proposta «Risolto» nella pagina «Proposte di chiusura», con le prove calcolate dal
portale (``ai_proposte.prove_alert``: ultima occorrenza, esecuzioni del job dopo l'alert, report sullo stesso
soggetto). La persona conferma, corregge o scarta come per le proposte dell'AI, e ogni decisione insegna allo
stesso modo. Mai per CVE (si chiudono con le prove PC per PC), alert critici o malware. Una proposta per alert:
se una persona la scarta, l'alert non viene riproposto finché non arriva una nuova occorrenza.
"""
from __future__ import annotations

from datetime import timedelta

from django.db.models import F
from django.utils import timezone

from security.models import SecurityAlert, SecurityAlertProposta, Severity
from security.services import soc_settings
from security.services.alert_lifecycle import DA_DECIDERE_ALERT_STATUSES

MODELLO = "regola: alert fermo"
TIPI_ESCLUSI = ("cve_impact_confirmed", "cve_sla_scaduta", "vulnerability_finding", "veeam_malware",
                "defender_alert", "defender_incident", "dipendenza_vulnerabile")
PAROLE_ESCLUSE = ("malware", "ransomware", "virus", "exploit", "botnet", "apt")
MAX_PER_GIRO = 200


def giorni() -> int:
    from security.services.alert_doppioni import rumore_attivo

    return soc_settings.value("rumore.fermi.giorni") if rumore_attivo() else 0


def candidati(now=None):
    """Alert «da decidere» fermi da almeno ``giorni()`` giorni, senza proposte dopo l'ultima occorrenza."""
    n = giorni()
    if not n:
        return SecurityAlert.objects.none()
    limite = (now or timezone.now()) - timedelta(days=n)
    qs = (SecurityAlert.objects.filter(status__in=DA_DECIDERE_ALERT_STATUSES, created_at__lt=limite, updated_at__lt=limite)
          .exclude(severity=Severity.CRITICAL)
          .exclude(event__event_type__in=TIPI_ESCLUSI)
          .exclude(proposte_ai__stato=SecurityAlertProposta.APERTA)
          .exclude(proposte_ai__creata_il__gte=F("updated_at")))
    for parola in PAROLE_ESCLUSE:
        qs = qs.exclude(title__icontains=parola)
    return qs.select_related("event", "source").distinct().order_by("updated_at")


def proponi_chiusura(now=None) -> int:
    """Una proposta «Risolto» per ogni alert fermo. Torna quante ne ha create."""
    from security.services import ai_proposte

    now = now or timezone.now()
    n = giorni()
    creati = 0
    for alert in candidati(now)[:MAX_PER_GIRO]:
        prove = [f"P{i}: {testo}" for i, testo in enumerate(ai_proposte.prove_alert(alert, now=now), start=1)]
        if not prove:
            continue
        schema, etichetta = ai_proposte.schema_di(alert)
        SecurityAlertProposta.objects.create(
            alert=alert, schema=schema, schema_label=etichetta, impronta=ai_proposte._impronta(alert), esito="resolved",
            motivo=(f"Nessuna nuova occorrenza da almeno {n} giorni (ultimo aggiornamento il "
                    f"{timezone.localtime(alert.updated_at):%d/%m/%Y}): il problema non si è ripresentato."),
            prove=prove, confidenza=50, modello=MODELLO, creata_il=now,
        )
        creati += 1
    return creati
