"""Task django-q del modulo procedure_refresh.

``run_sgi_share_check``: watchdog che rileva i documenti SGI **nuovi/aggiornati**
sulla share non ancora importati e apre una Issue **informativa** nella centrale
monitoring. L'import resta un'azione **umana** (``import_sgi_da_share --apply`` +
``index_sgi_documents``): qui si NOTIFICA soltanto. Fail-safe assoluto.

``run_assignment_lifecycle``: motore scadenze della presa visione (ISO 9001/EN
9100, distribuzione controllata). Marca **sempre** OVERDUE le assegnazioni
scadute (stato dei dati, evidenza audit); con i solleciti attivi
(``pr_reminder_attivo``) invia promemoria pre-scadenza, solleciti post-scadenza
e il digest inadempienti ai gestori. Email SEMPRE su ``email_notifica``
dell'anagrafica (mai il campo ``email`` legacy, che è il login).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

_CHECK_NAME = "sgi_share_drift"

# Ordine settimana coerente con reminder_config.GIORNI_VALIDI (lun=0 ... dom=6).
_WEEKDAYS = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")


def _site_url() -> str:
    return str(getattr(settings, "SITE_URL", "") or "").rstrip("/")


def _legacy_id_map(user_ids: list[int]) -> dict[int, int]:
    """user.pk -> legacy_user_id (fallback: user.pk stesso). Difensivo."""
    result = {uid: uid for uid in user_ids}
    try:
        from core.models import Profile

        for row in Profile.objects.filter(user_id__in=user_ids).values(
            "user_id", "legacy_user_id"
        ):
            if row["legacy_user_id"]:
                result[row["user_id"]] = int(row["legacy_user_id"])
    except Exception:
        logger.exception("procedure_refresh: lookup Profile fallito")
    return result


def _notification_email_map(user_ids: list[int]) -> dict[int, str]:
    """user.pk -> email di notifica ("" se assente: niente mail, resta la
    Notifica in-app). Risoluzione via anagrafica (``email_notifica``), MAI il
    campo ``email`` legacy che è il login."""
    result: dict[int, str] = {uid: "" for uid in user_ids}
    legacy_map = _legacy_id_map(user_ids)
    try:
        from core.legacy_anagrafica import resolve_notification_email
        from core.legacy_models import AnagraficaDipendente

        legacy_to_user = {v: k for k, v in legacy_map.items()}
        rows = AnagraficaDipendente.objects.filter(
            utente_id__in=set(legacy_map.values())
        ).values("utente_id", "email", "email_notifica")
        for row in rows:
            uid = legacy_to_user.get(row["utente_id"])
            if uid is None:
                continue
            addr = resolve_notification_email(
                email=row.get("email") or "",
                email_notifica=row.get("email_notifica") or "",
            )
            if addr and "@" in addr:
                result[uid] = addr
    except Exception:
        logger.exception("procedure_refresh: risoluzione email_notifica fallita")
    return result


def _has_reminder_event(assignment, kind: str, since=None) -> bool:
    from procedure_refresh.models import ProcedureReadEvent, ReadEventType

    qs = ProcedureReadEvent.objects.filter(
        assignment=assignment,
        event_type=ReadEventType.REMINDER_SENT,
        meta_json__contains=f'"kind": "{kind}"',
    )
    if since is not None:
        qs = qs.filter(event_at__gte=since)
    return qs.exists()


def _log_reminder_event(assignment, kind: str) -> None:
    from procedure_refresh.models import ProcedureReadEvent, ReadEventType

    ProcedureReadEvent.objects.create(
        assignment=assignment,
        event_type=ReadEventType.REMINDER_SENT,
        notes=f"Sollecito automatico ({kind}).",
        meta_json=json.dumps({"kind": kind}),
    )


def _send_reminder_mail(user, email: str, assignments: list, *, subject: str, intro: str) -> bool:
    """Una mail per utente con l'elenco dei documenti. Ritorna True se inviata."""
    if not email:
        return False
    from core.email_utils import send_hub_mail

    lines = [intro, ""]
    for a in assignments:
        doc = a.revision.document
        due = a.due_date.strftime("%d/%m/%Y") if a.due_date else "-"
        lines.append(f"- {doc.code} — {doc.title} (rev. {a.revision.revision_code}, scadenza {due})")
    lines += ["", "Accedi al portale per confermare la presa visione:",
              f"{_site_url()}/procedure-refresh/"]
    try:
        send_hub_mail(
            subject,
            "\n".join(lines),
            [email],
            title=subject,
            email_type="Presa Visione",
        )
        return True
    except Exception:
        logger.exception("procedure_refresh: invio sollecito fallito per %s", email)
        return False


def run_assignment_lifecycle(**kwargs) -> dict:
    """Motore scadenze presa visione. Fail-safe: non solleva mai."""
    result: dict = {
        "ok": True,
        "overdue_marked": 0,
        "pre_sent": 0,
        "post_sent": 0,
        "digest_sent": False,
    }
    try:
        from django.utils import timezone

        from core.notifiche import invia_notifica
        from procedure_refresh.models import (
            AssignmentStatus,
            CampaignStatus,
            ProcedureAssignment,
            ProcedureReadEvent,
            ReadEventType,
        )
        from procedure_refresh.reminder_config import get_reminder_config

        today = timezone.localdate()
        pending_statuses = [AssignmentStatus.ASSIGNED, AssignmentStatus.OPENED]

        # ── 1) Marcatura OVERDUE: SEMPRE, anche con solleciti spenti ─────────
        overdue_now = list(
            ProcedureAssignment.objects.filter(
                status__in=pending_statuses,
                campaign__status=CampaignStatus.PUBLISHED,
                due_date__isnull=False,
                due_date__lt=today,
            ).select_related("revision__document")
        )
        for assignment in overdue_now:
            assignment.status = AssignmentStatus.OVERDUE
            assignment.save(update_fields=["status", "updated_at"])
            ProcedureReadEvent.objects.create(
                assignment=assignment,
                event_type=ReadEventType.OVERDUE_MARKED,
                notes="Scadenza superata senza conferma (run_assignment_lifecycle).",
            )
            result["overdue_marked"] += 1

        cfg = get_reminder_config()
        if not cfg["attivo"]:
            return result

        # ── 2) Promemoria pre-scadenza (una mail per utente per soglia) ─────
        pre_pool = list(
            ProcedureAssignment.objects.filter(
                status__in=pending_statuses,
                campaign__status=CampaignStatus.PUBLISHED,
                due_date__isnull=False,
                due_date__gte=today,
            ).select_related("user", "revision__document", "campaign")
        )
        user_ids = sorted({a.user_id for a in pre_pool})
        email_map = _notification_email_map(user_ids) if user_ids else {}
        legacy_map = _legacy_id_map(user_ids) if user_ids else {}

        for soglia in cfg["pre_giorni"]:
            per_user: dict[int, list] = {}
            for a in pre_pool:
                if (a.due_date - today).days == soglia and not _has_reminder_event(a, f"pre{soglia}"):
                    per_user.setdefault(a.user_id, []).append(a)
            for uid, items in per_user.items():
                user = items[0].user
                subject = f"Presa visione: {len(items)} documenti in scadenza tra {soglia} giorni"
                sent = _send_reminder_mail(
                    user, email_map.get(uid, ""), items,
                    subject=subject,
                    intro="Hai documenti in presa visione non ancora confermati, in scadenza:",
                )
                invia_notifica(
                    legacy_map.get(uid), "generico",
                    f"{len(items)} documenti in presa visione scadono tra {soglia} giorni.",
                    url_azione="/procedure-refresh/",
                )
                for a in items:
                    _log_reminder_event(a, f"pre{soglia}")
                if sent:
                    result["pre_sent"] += len(items)

        # ── 3) Sollecito post-scadenza (cadenza configurabile) ──────────────
        overdue_pool = list(
            ProcedureAssignment.objects.filter(
                status=AssignmentStatus.OVERDUE,
                campaign__status=CampaignStatus.PUBLISHED,
            ).select_related("user", "revision__document", "campaign")
        )
        cadenza = cfg["post_cadenza_giorni"]
        since = timezone.now() - timezone.timedelta(days=cadenza)
        post_user_ids = sorted({a.user_id for a in overdue_pool})
        if post_user_ids:
            email_map.update(_notification_email_map([u for u in post_user_ids if u not in email_map]))
            legacy_map.update(_legacy_id_map([u for u in post_user_ids if u not in legacy_map]))
        per_user_post: dict[int, list] = {}
        for a in overdue_pool:
            if not _has_reminder_event(a, "post", since=since):
                per_user_post.setdefault(a.user_id, []).append(a)
        for uid, items in per_user_post.items():
            user = items[0].user
            subject = f"Presa visione SCADUTA: {len(items)} documenti da confermare"
            sent = _send_reminder_mail(
                user, email_map.get(uid, ""), items,
                subject=subject,
                intro="Hai documenti in presa visione con scadenza superata, da confermare al più presto:",
            )
            invia_notifica(
                legacy_map.get(uid), "generico",
                f"{len(items)} documenti in presa visione sono scaduti senza conferma.",
                url_azione="/procedure-refresh/?status=overdue",
            )
            for a in items:
                _log_reminder_event(a, "post")
            if sent:
                result["post_sent"] += len(items)

        # ── 4) Digest inadempienti ai gestori ────────────────────────────────
        digest_giorno = cfg["digest_giorno"]
        destinatari = cfg["digest_destinatari"]
        if digest_giorno and destinatari and _WEEKDAYS[today.weekday()] == digest_giorno:
            from core.models import SiteConfig

            last = str(SiteConfig.get("pr_reminder_digest_last", "") or "")
            if last != today.isoformat() and overdue_pool:
                from procedure_refresh.views import _user_department_map

                dep_map = _user_department_map([a.user for a in overdue_pool])
                by_campaign: dict[str, list] = {}
                for a in overdue_pool:
                    by_campaign.setdefault(a.campaign.name, []).append(a)
                lines = ["Assegnazioni di presa visione scadute e non confermate:", ""]
                for camp_name in sorted(by_campaign):
                    lines.append(f"Campagna: {camp_name}")
                    for a in sorted(
                        by_campaign[camp_name],
                        key=lambda x: (dep_map.get(x.user_id, ""), x.user.last_name or x.user.username),
                    ):
                        doc = a.revision.document
                        due = a.due_date.strftime("%d/%m/%Y") if a.due_date else "-"
                        nome = a.user.get_full_name() or a.user.username
                        lines.append(
                            f"- {nome} [{dep_map.get(a.user_id, 'Senza reparto')}] — "
                            f"{doc.code} {doc.title} (scadenza {due})"
                        )
                    lines.append("")
                lines.append(f"Report completo: {_site_url()}/procedure-refresh/admin/report/campagna/")
                from core.email_utils import send_hub_mail

                try:
                    send_hub_mail(
                        f"Presa visione: {len(overdue_pool)} assegnazioni scadute",
                        "\n".join(lines),
                        destinatari,
                        title="Digest inadempienti presa visione",
                        email_type="Presa Visione",
                    )
                    SiteConfig.set(
                        "pr_reminder_digest_last", today.isoformat(),
                        "Presa visione: data ultimo digest inadempienti inviato.",
                    )
                    result["digest_sent"] = True
                except Exception:
                    logger.exception("procedure_refresh: invio digest gestori fallito")

        return result
    except Exception as exc:  # fail-safe: il motore scadenze non deve rompere il cluster
        logger.exception("run_assignment_lifecycle fallito: %s", exc)
        result.update(ok=False, error=str(exc))
        return result


def run_sgi_share_check(**kwargs) -> dict:
    """Confronta la share SGI col DB e apre/risolve una Issue se ci sono documenti
    nuovi o con revisione più alta da importare. Ritorna un riepilogo (per i log/test).
    Non scrive mai sui documenti."""
    result: dict = {"ok": True, "skipped": False, "new": 0, "updated": 0}
    try:
        raw_root = str(getattr(settings, "PROCEDURE_REFRESH_SGI_SHARE_ROOT", "") or "").strip()
        if not raw_root:
            result.update(skipped=True, reason="PROCEDURE_REFRESH_SGI_SHARE_ROOT non impostato")
            return result
        root = Path(raw_root)
        if not root.exists():
            result.update(skipped=True, reason=f"root non raggiungibile: {raw_root}")
            return result

        from procedure_refresh.management.commands.import_sgi_da_share import detect_share_drift

        drift = detect_share_drift(root)
        n_new, n_upd = len(drift["new"]), len(drift["updated"])
        result.update(new=n_new, updated=n_upd, in_db=drift.get("in_db", 0))

        try:
            from monitoring.models import Issue
            from monitoring.services import (
                open_or_update_issue_from_health_check,
                resolve_health_check_issue,
            )
        except Exception:
            # monitoring non disponibile: il risultato resta nei log, niente Issue.
            logger.info("sgi_share_check: nuovi=%d aggiornati=%d (monitoring assente)", n_new, n_upd)
            return result

        if n_new or n_upd:
            sample = ", ".join(d["code"] for d in (drift["new"] + drift["updated"])[:10])
            open_or_update_issue_from_health_check(
                check_name=_CHECK_NAME,
                title=f"SGI: {n_new} documenti nuovi + {n_upd} aggiornati da importare",
                message=(
                    f"Documenti sulla share non ancora indicizzati dall'AI (es.: {sample}). "
                    "Azione umana: `manage.py import_sgi_da_share --apply` poi `index_sgi_documents`."
                ),
                severity=Issue.Severity.LOW,
                module_name="procedure_refresh",
                extra_json={"new": drift["new"][:50], "updated": drift["updated"][:50]},
                notify=False,  # informativo: compare in "Stato sistema", niente email
            )
        else:
            resolve_health_check_issue(
                check_name=_CHECK_NAME,
                summary="Nessun documento SGI nuovo/aggiornato sulla share.",
            )
        return result
    except Exception as exc:  # fail-safe: un watchdog non deve mai far rumore in cluster
        logger.warning("run_sgi_share_check fallito: %s", exc)
        result.update(ok=False, error=str(exc))
        return result
