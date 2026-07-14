"""Invia promemoria email per scadenze manutenzione imminenti.

Schedulare come task Windows quotidiano (suggerito alle 07:00):

    python manage.py send_maintenance_reminders

Controlla:
  1. Tutto ciò che è già SCADUTO (scadenze amministrative, verifiche periodiche, manutenzioni
     da regola): resta nella mail, in cima, finché non viene risolto.
  2. AssetAdministrativeDeadline in scadenza entro --deadline-days (default: 30)
  3. PeriodicVerification in scadenza entro --deadline-days
  4. WorkOrder aperti da più di --wo-overdue-days (0 = SiteConfig "assets_wo_overdue_days", default 21)
  5. Manutenzioni programmate dalle REGOLE (MaintenanceRule) in warning entro --deadline-days
  6. Manutenzioni NON VALUTABILI (contatore mancante o mai eseguite) e CONTATORI FERMI:
     un contatore non aggiornato produce scadenze verdi ma false.

Destinatari: SiteConfig chiave "assets_reminder_emails" (lista separata da virgola),
  oppure settings.ADMINS, oppure utenti superuser con email.
Soglia giorni configurabile anche via SiteConfig chiave "assets_reminder_days" (default: 30).
Contatore fermo: SiteConfig chiave "assets_meter_stale_days" (default: 30).

Cadenza (anti-rumore): ciò che è scaduto/non valutabile è nella mail TUTTI i giorni; ciò che è
solo in scadenza compare il primo giorno in cui entra nella finestra di preavviso, poi una volta
a settimana, poi il giorno della scadenza. Con --no-throttle si manda tutto, ogni giorno.

Idempotente: eseguire più volte nello stesso giorno invia più email (nessun flag fired).
Per ambienti di test usare --dry-run.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from assets.models import AssetAdministrativeDeadline, PeriodicVerification, WorkOrder
from assets.notifications import notify_user_about_workorder
from core.models import SiteConfig
from core.notifiche import invia_notifica_email


def should_remind_upcoming(days_left: int | None, window_days: int) -> bool:
    """Cadenza dei promemoria per ciò che NON è ancora scaduto.

    Con 30 giorni di preavviso la stessa scadenza finiva nella mail per 30 mattine identiche:
    è il modo canonico per rendere invisibile un alert. Qui si avvisa il primo giorno in cui la
    scadenza entra nella finestra, poi una volta a settimana, poi il giorno stesso della scadenza.
    Le righe senza un conteggio di giorni (regole a contatore) restano sempre incluse.
    """
    if days_left is None:
        return True
    if days_left <= 0:
        return True
    window = max(1, int(window_days or 0))
    if days_left >= window:
        return True
    return (window - days_left) % 7 == 0


def _rule_row_line(row: dict) -> str:
    """Riga leggibile per una manutenzione da regola (scadenzario rule-based)."""
    asset = row["asset"]
    label = getattr(row.get("effective_intervention_template"), "label", "") or "Manutenzione"
    base_rule = row["base_rule"]
    ext = ""
    if base_rule.is_external:
        supplier = f" {base_rule.supplier}" if base_rule.supplier_id else ""
        ext = f" [esterna{supplier}]"
    due = row.get("due_date")
    due_str = due.strftime("%d-%m-%Y") if due else (str(row.get("schedule_label") or "") or "—")
    return f"{asset.asset_tag} — {label}{ext} — {due_str}"


def _get_recipients(override: list[str] | None) -> list[str]:
    # Delega alla cascata unica (override → SiteConfig → ADMINS → superuser).
    from core.reminder_recipients import resolve_reminder_recipients

    return resolve_reminder_recipients(config_key="assets_reminder_emails", override=override)


class Command(BaseCommand):
    help = "Invia email promemoria per scadenze manutenzione e OdL aperti in ritardo."

    def add_arguments(self, parser):
        parser.add_argument(
            "--deadline-days",
            type=int,
            default=0,
            help="Giorni di anticipo per scadenze/verifiche (0 = legge da SiteConfig 'assets_reminder_days', default 30).",
        )
        parser.add_argument(
            "--wo-overdue-days",
            type=int,
            default=0,
            help="OdL aperti da più di N giorni (0 = legge da SiteConfig 'assets_wo_overdue_days', default 21).",
        )
        parser.add_argument(
            "--recipients",
            nargs="*",
            help="Email destinatari (sovrascrive SiteConfig/ADMINS).",
        )
        parser.add_argument(
            "--no-throttle",
            action="store_true",
            help="Ignora la cadenza anti-rumore: include tutte le voci in scadenza, non solo quelle del giorno.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare email.")

    def handle(self, *args, **options):
        from assets.maintenance import get_workorder_overdue_days

        dry_run: bool = bool(options.get("dry_run"))
        no_throttle: bool = bool(options.get("no_throttle"))
        wo_overdue_days: int = int(options.get("wo_overdue_days") or 0) or get_workorder_overdue_days()
        recipients: list[str] = _get_recipients(options.get("recipients") or [])

        raw_days = int(options.get("deadline_days") or 0)
        if raw_days <= 0:
            try:
                raw_days = int(SiteConfig.get("assets_reminder_days", "30") or "30")
            except (ValueError, TypeError):
                raw_days = 30
        deadline_days = max(1, raw_days)

        today = timezone.localdate()
        horizon = today + timedelta(days=deadline_days)
        wo_threshold = today - timedelta(days=wo_overdue_days)

        # 1. Scadenze amministrative: scadute (sempre, finché non risolte) + in scadenza entro l'orizzonte.
        #    Nessun filtro di finestra futura: una scadenza superata deve gridare di più, non sparire.
        admin_all = list(
            AssetAdministrativeDeadline.objects.filter(
                is_active=True,
                due_date__lte=horizon,
            )
            .select_related("asset")
            .order_by("due_date")
        )
        admin_overdue = [d for d in admin_all if d.due_date < today]
        admin_deadlines = [
            d
            for d in admin_all
            if d.due_date >= today
            and (no_throttle or should_remind_upcoming((d.due_date - today).days, deadline_days))
        ]

        # 2. Verifiche periodiche: idem, scadute + in scadenza.
        #    is_legacy=True significa "trigger temporale gestito dalle MaintenanceRule": la stessa
        #    manutenzione arriverebbe due volte nella mail. Cockpit e KPI le escludono già.
        periodic_all = list(
            PeriodicVerification.objects.filter(
                is_active=True,
                is_legacy=False,
                next_verification_date__isnull=False,
                next_verification_date__lte=horizon,
            )
            .order_by("next_verification_date")
        )
        periodic_overdue = [v for v in periodic_all if v.next_verification_date < today]
        periodic = [
            v
            for v in periodic_all
            if v.next_verification_date >= today
            and (
                no_throttle
                or should_remind_upcoming((v.next_verification_date - today).days, deadline_days)
            )
        ]

        # 3. OdL aperti in ritardo
        overdue_wo = list(
            WorkOrder.objects.filter(
                status=WorkOrder.STATUS_OPEN,
                opened_at__date__lte=wo_threshold,
            )
            .select_related("asset", "assigned_to")
            .order_by("opened_at")
        )

        # 4. Manutenzioni programmate dalle REGOLE: scadute + in warning entro l'orizzonte,
        #    più le righe non valutabili (contatore mancante / mai eseguite) e i contatori fermi.
        #    (Prima non erano coperte dai reminder: lo scadenzario rule-based era solo "pull".)
        from assets.maintenance import build_maintenance_schedule_rows, get_meter_stale_days

        stale_days = get_meter_stale_days()
        rule_overdue: list[dict] = []
        rule_due: list[dict] = []
        rule_missing: list[dict] = []
        stale_meters: dict[tuple[int, str], dict] = {}
        for row in build_maintenance_schedule_rows(today=today):
            if row.get("meter_is_stale"):
                # Un contatore fermo serve la stessa bugia ("restano 320 h") a tutte le regole
                # che lo usano: nella mail va segnalato una volta sola.
                stale_meters.setdefault((row["asset"].id, str(row.get("meter_unit") or "")), row)
            status = str(row.get("schedule_status") or "")
            if status == "missing":
                rule_missing.append(row)
                continue
            if status not in ("overdue", "warning"):
                continue
            days = row.get("days_until_due")
            if status == "overdue":
                rule_overdue.append(row)
                continue
            if isinstance(days, int) and days > deadline_days:
                continue
            warning_window = int(row.get("effective_warning_days") or 0) or deadline_days
            if not no_throttle and not should_remind_upcoming(days, warning_window):
                continue
            rule_due.append(row)
        rule_overdue.sort(key=lambda r: (r.get("days_until_due") if isinstance(r.get("days_until_due"), int) else 0))
        rule_due.sort(key=lambda r: (r.get("days_until_due") or 0))
        # cap difensivo sull'email
        rule_overdue = rule_overdue[:50]
        rule_due = rule_due[:50]
        rule_missing = rule_missing[:50]
        meter_stale = list(stale_meters.values())[:50]

        overdue_total = len(admin_overdue) + len(periodic_overdue) + len(rule_overdue)

        if not (
            overdue_total
            or admin_deadlines
            or periodic
            or overdue_wo
            or rule_due
            or rule_missing
            or meter_stale
        ):
            self.stdout.write("Nessun promemoria da inviare.")
            return

        lines = [
            f"NOVICROM HUB — Promemoria manutenzione del {today:%d-%m-%Y}",
            "=" * 60,
            "",
        ]

        if overdue_total:
            lines.append("!!! SCADUTE — AZIONE IMMEDIATA " + "!" * 29)
            lines.append(f"{overdue_total} voci hanno superato la scadenza e restano qui finché non vengono risolte.")
            lines.append("")
            for d in admin_overdue:
                late = (today - d.due_date).days
                lines.append(
                    f"  [SCADUTA da {late}gg] Scadenza amministrativa — {d.asset.asset_tag} — {d.title} "
                    f"— era il {d.due_date:%d-%m-%Y}"
                )
            for v in periodic_overdue:
                late = (today - v.next_verification_date).days
                lines.append(
                    f"  [SCADUTA da {late}gg] Verifica periodica — {v.name} "
                    f"— era il {v.next_verification_date:%d-%m-%Y}"
                )
            for row in rule_overdue:
                lines.append(f"  [SCADUTA] Manutenzione programmata — {_rule_row_line(row)}")
            lines.append("")
            lines.append("=" * 60)
            lines.append("")

        if rule_missing:
            lines.append(f"NON VALUTABILI — contatore mancante o mai eseguite ({len(rule_missing)}):")
            for row in rule_missing:
                lines.append(f"  {_rule_row_line(row)}")
            lines.append("")

        if meter_stale:
            lines.append(f"CONTATORI FERMI DA ALMENO {stale_days} GIORNI ({len(meter_stale)}):")
            lines.append("  Finché non vengono letti, le scadenze a contatore di questi asset non sono attendibili.")
            for row in meter_stale:
                asset = row["asset"]
                unit = row.get("meter_unit") or "u"
                lines.append(
                    f"  [{row.get('meter_days_since_update')}gg senza letture] {asset.asset_tag} — "
                    f"contatore {unit}: {row.get('meter_current_value')}"
                )
            lines.append("")

        if admin_deadlines:
            lines.append(f"SCADENZE AMMINISTRATIVE nei prossimi {deadline_days} giorni ({len(admin_deadlines)}):")
            for d in admin_deadlines:
                days_left = (d.due_date - today).days
                lines.append(f"  [{days_left}gg] {d.asset.asset_tag} — {d.title} — scadenza {d.due_date:%d-%m-%Y}")
            lines.append("")

        if periodic:
            lines.append(f"VERIFICHE PERIODICHE nei prossimi {deadline_days} giorni ({len(periodic)}):")
            for v in periodic:
                days_left = (v.next_verification_date - today).days
                lines.append(f"  [{days_left}gg] {v.name} — {v.next_verification_date:%d-%m-%Y}")
            lines.append("")

        if rule_due:
            lines.append(f"MANUTENZIONI PROGRAMMATE (regole) in scadenza ({len(rule_due)}):")
            for row in rule_due:
                lines.append(f"  [in scadenza] {_rule_row_line(row)}")
            lines.append("")

        if overdue_wo:
            lines.append(f"OdL APERTI DA PIÙ DI {wo_overdue_days} GIORNI ({len(overdue_wo)}):")
            for wo in overdue_wo:
                age = (today - wo.opened_at.date()).days
                lines.append(f"  [{age}gg] #{wo.pk} {wo.asset.asset_tag} — {wo.title}")
            lines.append("")

        body = "\n".join(lines)
        subject_parts: list[str] = []
        if overdue_total:
            subject_parts.append(f"{overdue_total} SCADUTE")
        if rule_missing:
            subject_parts.append(f"{len(rule_missing)} non valutabili")
        if meter_stale:
            subject_parts.append(f"{len(meter_stale)} contatori fermi")
        subject_parts.extend(
            [
                f"{len(rule_due)} regole",
                f"{len(admin_deadlines)} scad.",
                f"{len(periodic)} verif.",
                f"{len(overdue_wo)} OdL",
            ]
        )
        subject = f"[Manutenzione] {' + '.join(subject_parts)} — {today:%d-%m-%Y}"

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna email inviata."))
            self.stdout.write(f"Destinatari: {recipients}")
            self.stdout.write(body)
            return

        if not recipients:
            self.stdout.write(self.style.ERROR("Nessun destinatario configurato. Usare --recipients o impostare SiteConfig 'assets_reminder_emails'."))
            return

        try:
            from automazioni.mail_config import apply_mail_overrides
            from core.email_utils import send_hub_mail
            subject, body, fragment, footer = apply_mail_overrides(
                "assets_maintenance_reminders", subject=subject, body_text=body)
            send_hub_mail(
                subject, body, recipients,
                email_type="Assets",
                section_label="Reminder manutenzione",
                body_html_fragment=fragment,
                footer_note=footer,
                fail_silently=False,
            )
            for email in recipients:
                for d in admin_overdue:
                    late = (today - d.due_date).days
                    invia_notifica_email(
                        email,
                        "asset_scadenza",
                        f"SCADUTA da {late} giorni: {d.asset.asset_tag} - {d.title}.",
                        f"/assets/scadenze/?focus_deadline={d.pk}",
                    )
                for v in periodic_overdue:
                    late = (today - v.next_verification_date).days
                    invia_notifica_email(
                        email,
                        "asset_scadenza",
                        f"Verifica periodica SCADUTA da {late} giorni: {v.name}.",
                        f"/assets/manutenzione/verifiche/?edit={v.pk}",
                    )
                for row in rule_overdue:
                    asset = row["asset"]
                    label = getattr(row.get("effective_intervention_template"), "label", "") or "Manutenzione"
                    invia_notifica_email(
                        email,
                        "asset_scadenza",
                        f"Manutenzione SCADUTA: {asset.asset_tag} - {label}.",
                        f"/assets/manutenzione/prossime/?asset={asset.id}&status=due",
                    )
                for row in rule_missing:
                    asset = row["asset"]
                    label = getattr(row.get("effective_intervention_template"), "label", "") or "Manutenzione"
                    invia_notifica_email(
                        email,
                        "asset_scadenza",
                        f"Manutenzione non valutabile ({row.get('schedule_label')}): {asset.asset_tag} - {label}.",
                        f"/assets/manutenzione/prossime/?asset={asset.id}",
                    )
                for row in meter_stale:
                    asset = row["asset"]
                    unit = row.get("meter_unit") or "u"
                    invia_notifica_email(
                        email,
                        "asset_scadenza",
                        f"Contatore {unit} fermo da {row.get('meter_days_since_update')} giorni: "
                        f"{asset.asset_tag}. Le scadenze a contatore non sono attendibili.",
                        f"/assets/{asset.id}/",
                    )
                for d in admin_deadlines:
                    days_left = (d.due_date - today).days
                    invia_notifica_email(
                        email,
                        "asset_scadenza",
                        f"Scadenza asset tra {days_left} giorni: {d.asset.asset_tag} - {d.title}.",
                        f"/assets/scadenze/?focus_deadline={d.pk}",
                    )
                for v in periodic:
                    days_left = (v.next_verification_date - today).days
                    invia_notifica_email(
                        email,
                        "asset_scadenza",
                        f"Verifica periodica in scadenza tra {days_left} giorni: {v.name}.",
                        f"/assets/manutenzione/verifiche/?edit={v.pk}",
                    )
                for wo in overdue_wo:
                    age = (today - wo.opened_at.date()).days
                    invia_notifica_email(
                        email,
                        "asset_scadenza",
                        f"OdL aperto da {age} giorni: #{wo.pk} {wo.asset.asset_tag} - {wo.title}.",
                        f"/assets/workorders/view/{wo.pk}/",
                    )
                for row in rule_due:
                    asset = row["asset"]
                    label = getattr(row.get("effective_intervention_template"), "label", "") or "Manutenzione"
                    invia_notifica_email(
                        email,
                        "asset_scadenza",
                        f"Manutenzione in scadenza: {asset.asset_tag} - {label}.",
                        f"/assets/manutenzione/prossime/?asset={asset.id}&status=due",
                    )
            # L'OdL in ritardo va anche a chi deve farlo, non solo alla lista collettiva.
            personal = 0
            for wo in overdue_wo:
                if wo.assigned_to_id is None:
                    continue
                age = (today - wo.opened_at.date()).days
                if notify_user_about_workorder(
                    wo.assigned_to,
                    wo,
                    f"Il tuo intervento #{wo.pk} è aperto da {age} giorni: {wo.title} ({wo.asset.asset_tag}).",
                ):
                    personal += 1
            self.stdout.write(self.style.SUCCESS(
                f"Email inviata a {len(recipients)} destinatari. "
                f"Scadute={overdue_total} NonValutabili={len(rule_missing)} "
                f"ContatoriFermi={len(meter_stale)} Scadenze={len(admin_deadlines)} "
                f"Verifiche={len(periodic)} OdL_ritardo={len(overdue_wo)} "
                f"NotificheAssegnatari={personal}"
            ))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Invio email fallito: {exc}"))
