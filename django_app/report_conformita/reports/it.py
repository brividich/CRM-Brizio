"""Report area Sicurezza delle informazioni (ISO 27001)."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from ..people import cessati_ids
from ..registry import (
    AREA_IT,
    ISO_27001,
    ISO_9001,
    TONE_DANGER,
    TONE_OK,
    TONE_WARN,
    Kpi,
    ReportDef,
    ReportParams,
    ReportResult,
    c,
    register,
)
from ._common import d, links, pct, scadenza_stato, yes_no

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Inventario asset informatici
# ---------------------------------------------------------------------------


def _inventario_it(params: ReportParams) -> ReportResult:
    from assets.forms import IT_DEVICE_TYPES
    from assets.models import Asset

    result = ReportResult()
    assets = list(
        Asset.objects.filter(asset_type__in=IT_DEVICE_TYPES)
        .exclude(status="RETIRED")
        .order_by("asset_type", "asset_tag")
    )
    per_tipo = defaultdict(int)
    senza_resp = senza_seriale = 0
    result.columns = ["Tag", "Nome", "Tipo", "Marca / modello", "Seriale", "Reparto", "Assegnato a", "Stato"]
    for a in assets:
        per_tipo[a.get_asset_type_display()] += 1
        assegnato = a.assignment_to or ""
        reparto = a.assignment_reparto or a.reparto or ""
        tone = ""
        if not assegnato and not reparto:
            senza_resp += 1
            tone = TONE_WARN
        if not (a.serial_number or "").strip():
            senza_seriale += 1
        result.add_row(
            [a.asset_tag, a.name, a.get_asset_type_display(), " ".join(x for x in (a.manufacturer, a.model) if x),
             a.serial_number, reparto, assegnato, a.get_status_display()],
            tone,
        )
    totale = len(assets)
    result.kpis = [Kpi("Asset IT in inventario", totale)]
    for tipo, n in sorted(per_tipo.items(), key=lambda x: -x[1])[:4]:
        result.kpis.append(Kpi(tipo, n))
    result.kpis += [
        Kpi("Senza assegnatario né reparto", senza_resp, TONE_WARN if senza_resp else TONE_OK),
        Kpi("Senza numero di serie", senza_seriale, TONE_WARN if senza_seriale else ""),
    ]
    result.notes = [
        "Dispositivi IT non dismessi (PC, server, rete, fonia, stampanti, TVCC).",
        "ISO 27001 A.5.9 chiede un inventario con un proprietario per ogni asset: le righe evidenziate ne sono prive.",
    ]
    result.links = links(("Dispositivi IT", "assets:device_list"))
    return result


register(ReportDef(
    slug="inventario-it",
    title="Inventario degli asset informatici",
    area=AREA_IT,
    description="Dispositivi IT in uso con assegnatario, reparto e stato.",
    clausole=(c(ISO_27001, "A.5.9"), c(ISO_27001, "A.5.11"), c(ISO_9001, "7.1.3")),
    builder=_inventario_it,
    usa_periodo=False,
    fonte="Asset › Dispositivi IT",
))


# ---------------------------------------------------------------------------
# Licenze software
# ---------------------------------------------------------------------------


def _licenze(params: ReportParams) -> ReportResult:
    from assets.models import SoftwareLicense

    result = ReportResult()
    licenze = list(SoftwareLicense.objects.filter(is_active=True).order_by("expiry_date", "vendor", "product_name"))
    scadute = in_scad = sature = 0
    result.columns = ["Prodotto", "Fornitore", "Categoria", "Assegnata a", "Posti usati / totali",
                      "Rinnovo", "Scadenza", "Rinnovo automatico", "Stato"]
    for lic in licenze:
        scad = lic.expiry_date or lic.renewal_date
        if scad:
            stato, tone = scadenza_stato(scad, params.today)
        else:
            stato, tone = "Senza scadenza", ""
        if tone == TONE_DANGER:
            scadute += 1
        elif tone == TONE_WARN:
            in_scad += 1
        posti = ""
        if lic.seats_total:
            posti = f"{lic.seats_used or 0} / {lic.seats_total}"
            if (lic.seats_used or 0) > lic.seats_total:
                sature += 1
                stato, tone = "Posti oltre il licenziato", TONE_DANGER
        result.add_row(
            [" ".join(x for x in (lic.product_name, lic.edition) if x), lic.vendor, lic.get_category_display(),
             lic.assigned_to_display or lic.assigned_reparto, posti, d(lic.renewal_date), d(lic.expiry_date),
             yes_no(lic.auto_renew), stato],
            tone,
        )
    result.kpis = [
        Kpi("Licenze attive", len(licenze)),
        Kpi("Scadute", scadute, TONE_DANGER if scadute else TONE_OK),
        Kpi("In scadenza 30 gg", in_scad, TONE_WARN if in_scad else ""),
        Kpi("Posti oltre il licenziato", sature, TONE_DANGER if sature else TONE_OK),
    ]
    result.notes = ["ISO 27001 A.5.32: uso del software nel rispetto dei diritti di proprietà intellettuale e delle licenze."]
    result.links = links(("Licenze", "assets:software_license_list"))
    return result


register(ReportDef(
    slug="licenze-software",
    title="Licenze software",
    area=AREA_IT,
    description="Licenze attive, scadenze, posti utilizzati oltre il licenziato.",
    clausole=(c(ISO_27001, "A.5.32"), c(ISO_27001, "A.5.9")),
    builder=_licenze,
    usa_periodo=False,
    fonte="Asset › Licenze",
))


# ---------------------------------------------------------------------------
# Revisione degli accessi
# ---------------------------------------------------------------------------


def _legacy_user_ids_cessati(today) -> set[int]:
    try:
        from core.legacy_models import AnagraficaDipendente

        ids = cessati_ids(today)
        if not ids:
            return set()
        return {
            int(x)
            for x in AnagraficaDipendente.objects.filter(pk__in=ids, utente_id__isnull=False).values_list(
                "utente_id", flat=True
            )
        }
    except Exception:
        logger.warning("revisione accessi: legame utente-dipendente non leggibile", exc_info=True)
        return set()


def _revisione_accessi(params: ReportParams) -> ReportResult:
    from django.contrib.auth import get_user_model

    from core.models import AclDenialEvent, Profile

    result = ReportResult()
    User = get_user_model()
    utenti = list(User.objects.filter(is_active=True).order_by("username"))
    profili = {p.user_id: p for p in Profile.objects.filter(user__in=utenti)}

    twofa: dict[int, bool] = {}
    try:
        from twofa.models import UserTwoFactor

        twofa = {
            row.user_id: bool(row.is_active and (row.method != "totp" or row.totp_confirmed))
            for row in UserTwoFactor.objects.filter(user__in=utenti)
        }
    except Exception:
        logger.warning("revisione accessi: 2FA non leggibile", exc_info=True)

    negati = dict(
        AclDenialEvent.objects.filter(status="open")
        .order_by()
        .values("legacy_user_id")
        .annotate(n=Count("id"))
        .values_list("legacy_user_id", "n")
    )
    cessati_legacy = _legacy_user_ids_cessati(params.today)
    soglia_inattivo = timezone.now() - timedelta(days=90)

    n_2fa = n_inattivi = n_mai = n_cessati = n_super = 0
    result.columns = ["Utente", "Nome", "Ruolo", "Amministratore", "Ultimo accesso", "2FA",
                      "Accessi negati aperti", "Esito"]
    for u in utenti:
        profilo = profili.get(u.id)
        legacy_id = getattr(profilo, "legacy_user_id", None)
        ha_2fa = twofa.get(u.id, False)
        n_2fa += int(ha_2fa)
        n_super += int(u.is_superuser)
        esiti, tone = [], ""
        if legacy_id and int(legacy_id) in cessati_legacy:
            esiti.append("Dipendente cessato con utenza attiva")
            tone = TONE_DANGER
            n_cessati += 1
        if not u.last_login:
            esiti.append("Mai collegato")
            tone = tone or TONE_WARN
            n_mai += 1
        elif u.last_login < soglia_inattivo:
            esiti.append("Inattivo da oltre 90 gg")
            tone = tone or TONE_WARN
            n_inattivi += 1
        if u.is_superuser and not ha_2fa:
            esiti.append("Amministratore senza 2FA")
            tone = TONE_DANGER
        result.add_row(
            [u.username, u.get_full_name(), getattr(profilo, "legacy_ruolo", "") or "",
             yes_no(u.is_superuser or u.is_staff), d(u.last_login), yes_no(ha_2fa),
             negati.get(legacy_id, 0) if legacy_id else 0, "; ".join(esiti) or "OK"],
            tone,
        )
    totale = len(utenti)
    offboarding_chiuse = 0
    try:
        from anagrafica.models import OffboardingPratica

        offboarding_chiuse = OffboardingPratica.objects.filter(
            stato__in=("CHIUSA", "CHIUSA_CON_ECCEZIONI"), closed_at__date__range=(params.date_from, params.date_to)
        ).count()
    except Exception:
        logger.warning("revisione accessi: offboarding non leggibile", exc_info=True)

    result.kpis = [
        Kpi("Utenze attive", totale),
        Kpi("Con 2FA attiva", pct(n_2fa, totale), TONE_OK if totale and n_2fa == totale else TONE_WARN if totale else ""),
        Kpi("Amministratori", n_super),
        Kpi("Cessati con utenza attiva", n_cessati, TONE_DANGER if n_cessati else TONE_OK),
        Kpi("Inattive da oltre 90 gg", n_inattivi, TONE_WARN if n_inattivi else ""),
        Kpi("Mai collegate", n_mai, TONE_WARN if n_mai else ""),
        Kpi("Uscite chiuse nel periodo", offboarding_chiuse),
    ]
    result.notes = [
        "Revisione periodica dei diritti di accesso: da firmare e conservare come evidenza (ISO 27001 A.5.18).",
        "«Cessato» = dipendente con data di cessazione passata e utenza portale ancora attiva (A.6.5, A.5.18).",
        "Accessi negati aperti: richieste di permesso non ancora gestite in Admin › Accessi negati.",
    ]
    result.links = links(("Accessi negati", "admin_portale:accessi_negati"))
    return result


register(ReportDef(
    slug="revisione-accessi",
    title="Revisione degli accessi",
    area=AREA_IT,
    description="Utenze attive, 2FA, inattive, dipendenti cessati con utenza ancora attiva.",
    clausole=(c(ISO_27001, "A.5.15"), c(ISO_27001, "A.5.18"), c(ISO_27001, "A.8.5"), c(ISO_27001, "A.6.5")),
    builder=_revisione_accessi,
    fonte="Utenti, ACL, 2FA, Offboarding",
))


# ---------------------------------------------------------------------------
# Backup, vulnerabilita', rimedi
# ---------------------------------------------------------------------------

_APERTE = ("new", "open", "acknowledged", "in_progress")


def _esito_backup(status: str) -> str:
    s = (status or "").strip().lower()
    if any(k in s for k in ("fail", "error", "errore", "fallit")):
        return "ko"
    if "warn" in s:
        return "warn"
    if any(k in s for k in ("success", "ok", "complet", "riuscit")):
        return "ok"
    return "altro"


def _sicurezza_it(params: ReportParams) -> ReportResult:
    from security.models import BackupJobRecord, SecurityRemediationTicket, SecurityVulnerabilityFinding

    result = ReportResult()
    backup = defaultdict(int)
    for status in BackupJobRecord.objects.filter(
        started_at__date__range=(params.date_from, params.date_to)
    ).values_list("status", flat=True):
        backup[_esito_backup(status)] += 1
    tot_backup = sum(backup.values())

    vuln_aperte = SecurityVulnerabilityFinding.objects.filter(status__in=_APERTE)
    per_sev = dict(vuln_aperte.order_by().values("severity").annotate(n=Count("id")).values_list("severity", "n"))
    ticket_aperti = SecurityRemediationTicket.objects.filter(status__in=_APERTE).count()
    ticket_chiusi = SecurityRemediationTicket.objects.filter(
        status__in=("closed", "resolved"), updated_at__date__range=(params.date_from, params.date_to)
    ).count()

    result.columns = ["CVE", "Prodotto", "Gravità", "CVSS", "Dispositivi esposti", "Prima rilevazione", "Giorni aperta", "Stato"]
    for v in vuln_aperte.filter(severity__in=("critical", "high")).order_by("-cvss", "first_seen_at")[:300]:
        giorni = (params.today - timezone.localtime(v.first_seen_at).date()).days if v.first_seen_at else ""
        tone = TONE_DANGER if v.severity == "critical" or (isinstance(giorni, int) and giorni > 30) else TONE_WARN
        result.add_row(
            [v.cve, v.affected_product, v.get_severity_display(), v.cvss if v.cvss is not None else "",
             v.exposed_devices, d(v.first_seen_at), giorni, v.get_status_display()],
            tone,
        )
    result.kpis = [
        Kpi("Backup eseguiti nel periodo", tot_backup),
        Kpi("Backup riusciti", pct(backup["ok"], tot_backup),
            TONE_OK if tot_backup and backup["ok"] * 100 >= tot_backup * 98 else TONE_WARN if tot_backup else ""),
        Kpi("Backup falliti", backup["ko"], TONE_DANGER if backup["ko"] else TONE_OK),
        Kpi("Vulnerabilità critiche aperte", per_sev.get("critical", 0), TONE_DANGER if per_sev.get("critical") else TONE_OK),
        Kpi("Vulnerabilità alte aperte", per_sev.get("high", 0), TONE_WARN if per_sev.get("high") else ""),
        Kpi("Ticket di rimedio aperti", ticket_aperti),
        Kpi("Ticket chiusi nel periodo", ticket_chiusi),
    ]
    result.notes = [
        "Fonti: report acquisiti dal Security Center (job di backup, vulnerabilità da EDR/scanner, ticket di rimedio).",
        "Righe: vulnerabilità critiche e alte ancora aperte (massimo 300, per CVSS decrescente).",
    ]
    result.links = links(("Security Center", "security:dashboard"))
    return result


register(ReportDef(
    slug="sicurezza-it",
    title="Backup, vulnerabilità e rimedi",
    area=AREA_IT,
    description="Esito dei backup, vulnerabilità critiche/alte aperte, ticket di rimedio.",
    clausole=(c(ISO_27001, "A.8.13"), c(ISO_27001, "A.8.8"), c(ISO_27001, "A.5.26"), c(ISO_27001, "9.1")),
    builder=_sicurezza_it,
    fonte="Security Center",
))
