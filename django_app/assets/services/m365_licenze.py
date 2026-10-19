"""Abbonamenti Microsoft 365 nel modulo Licenze software (Microsoft Graph).

Ogni mattina (schedule ``m365_licenze_sync``) legge ``subscribedSkus`` (posti
acquistati, usati, stato) e, se il permesso lo consente, ``directory/subscriptions``
(data del prossimo rinnovo/scadenza). Per ogni abbonamento c'è una riga
``SoftwareLicense`` con ``license_reference = "m365:<skuPartNumber>"``: creata la
prima volta, poi aggiornata solo nei campi che vengono da Microsoft (posti,
stato, scadenza). Le licenze inserite a mano non vengono mai toccate.

Con la scadenza valorizzata, l'abbonamento entra da solo nello scadenzario e
nei promemoria delle licenze già esistenti.

Permessi Graph applicativi: ``Organization.Read.All`` (abbonamenti) e, per le
date, ``LicenseAssignment.Read.All`` o ``Directory.Read.All``. Sola lettura.
"""
from __future__ import annotations

import logging

from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger(__name__)

PERMESSO = "Organization.Read.All"
PERMESSO_DATE = "LicenseAssignment.Read.All"
PREFISSO = "m365:"
# Piani gratuiti o «virali» (10.000 posti finti): non sono licenze da gestire.
POSTI_FINTI = 10000

NOMI = {
    "SPB": "Microsoft 365 Business Premium",
    "O365_BUSINESS_PREMIUM": "Microsoft 365 Business Standard",
    "O365_BUSINESS_ESSENTIALS": "Microsoft 365 Business Basic",
    "O365_BUSINESS": "Microsoft 365 Apps for business",
    "SMB_BUSINESS": "Microsoft 365 Apps for business",
    "OFFICESUBSCRIPTION": "Microsoft 365 Apps for enterprise",
    "EXCHANGESTANDARD": "Exchange Online (Piano 1)",
    "EXCHANGEENTERPRISE": "Exchange Online (Piano 2)",
    "EXCHANGEDESKLESS": "Exchange Online Kiosk",
    "ENTERPRISEPACK": "Office 365 E3",
    "ENTERPRISEPREMIUM": "Office 365 E5",
    "SPE_E3": "Microsoft 365 E3",
    "SPE_E5": "Microsoft 365 E5",
    "SPE_F1": "Microsoft 365 F3",
    "DESKLESSPACK": "Office 365 F3",
    "POWER_BI_PRO": "Power BI Pro",
    "PBI_PREMIUM_PER_USER": "Power BI Premium per utente",
    "PROJECTPROFESSIONAL": "Project Plan 3",
    "VISIOCLIENT": "Visio Plan 2",
    "AAD_PREMIUM": "Microsoft Entra ID P1",
    "AAD_PREMIUM_P2": "Microsoft Entra ID P2",
    "INTUNE_A": "Microsoft Intune Plan 1",
    "ATP_ENTERPRISE": "Defender for Office 365 (Piano 1)",
    "THREAT_INTELLIGENCE": "Defender for Office 365 (Piano 2)",
    "MDATP_XPLAT": "Defender for Endpoint P2",
    "DEFENDER_ENDPOINT_P1": "Defender for Endpoint P1",
    "MCOEV": "Teams Phone Standard",
    "MCOPSTN1": "Teams Calling Plan (nazionale)",
    "TEAMS_ESSENTIALS": "Teams Essentials",
    "Microsoft_Teams_Premium": "Teams Premium",
    "Microsoft_365_Copilot": "Microsoft 365 Copilot",
}


def nome_leggibile(sku: str) -> str:
    return NOMI.get(sku, sku.replace("_", " ").title() if sku else "Abbonamento Microsoft 365")


def _scadenze(sku_ids: set[str]) -> dict[str, object]:
    """``skuId -> data`` del prossimo rinnovo/scadenza; vuoto se il permesso manca."""
    from core import m365_graph

    try:
        abbonamenti = m365_graph.get_all(f"{m365_graph.GRAPH}/directory/subscriptions", permesso=PERMESSO_DATE, max_pages=5)
    except m365_graph.GraphError as exc:
        logger.info("Licenze M365: date di rinnovo non leggibili (%s)", exc)
        return {}
    out: dict[str, object] = {}
    for a in abbonamenti:
        sku_id = str(a.get("skuId") or "")
        quando = parse_datetime(str(a.get("nextLifecycleDateTime") or "")) if a.get("nextLifecycleDateTime") else None
        if sku_id in sku_ids and quando:
            data = timezone.localtime(quando).date() if timezone.is_aware(quando) else quando.date()
            # Più abbonamenti dello stesso piano: conta il primo che scade.
            out[sku_id] = min(out[sku_id], data) if sku_id in out else data
    return out


def sincronizza(*, skus: list[dict] | None = None, scadenze: dict | None = None) -> dict:
    """Crea/aggiorna le righe ``m365:*``. ``skus``/``scadenze`` servono ai test."""
    from assets.models import SoftwareLicense
    from core import m365_graph

    if skus is None:
        skus = m365_graph.get_all(f"{m365_graph.GRAPH}/subscribedSkus", permesso=PERMESSO, max_pages=3)
    utili = []
    for s in skus:
        acquistati = int(((s.get("prepaidUnits") or {}).get("enabled")) or 0)
        if not s.get("skuPartNumber") or acquistati >= POSTI_FINTI or (acquistati == 0 and not s.get("consumedUnits")):
            continue
        utili.append(s)
    if scadenze is None:
        scadenze = _scadenze({str(s.get("skuId") or "") for s in utili})
    creati = aggiornati = 0
    visti = set()
    for s in utili:
        sku = str(s["skuPartNumber"])
        rif = f"{PREFISSO}{sku}"[:120]
        visti.add(rif)
        acquistati = int(((s.get("prepaidUnits") or {}).get("enabled")) or 0)
        usati = int(s.get("consumedUnits") or 0)
        attivo = str(s.get("capabilityStatus") or "Enabled") in ("Enabled", "Warning")
        lic = SoftwareLicense.objects.filter(license_reference=rif).first()
        if lic is None:
            lic = SoftwareLicense(
                license_reference=rif, category=SoftwareLicense.CATEGORY_OFFICE, vendor="Microsoft",
                product_name=nome_leggibile(sku)[:200],
                notes="Aggiornata ogni mattina da Microsoft 365: posti, stato e scadenza arrivano da Microsoft.",
            )
            creati += 1
        else:
            aggiornati += 1
        lic.seats_total = max(acquistati, usati)
        lic.seats_used = usati
        lic.is_active = attivo
        scadenza = scadenze.get(str(s.get("skuId") or ""))
        if scadenza:
            lic.expiry_date = scadenza
        lic.save()
    dismessi = (SoftwareLicense.objects.filter(license_reference__startswith=PREFISSO, is_active=True)
                .exclude(license_reference__in=visti).update(is_active=False))
    return {"abbonamenti": len(utili), "creati": creati, "aggiornati": aggiornati,
            "non_piu_presenti": dismessi, "con_scadenza": len(scadenze)}
