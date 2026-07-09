"""Promemoria email per i corsi di formazione OBBLIGATORIA scaduti o in scadenza.

Legge la cache ``TrainingDeadline`` (ricalcolata da ``refresh_training_deadlines``):
seleziona le scadenze obbligatorie (``is_required=True``) con stato SCADUTO o in
scadenza entro ``--days`` giorni, raggruppa per dipendente e produce un digest HR +
notifica in-app al dipendente. Pattern speculare a ``send_visite_expiry_reminders``.

Destinatari digest: override CLI → SiteConfig ``training_reminder_emails`` →
ADMINS → superuser. Le notifiche in-app al dipendente partono comunque.
Complementare al ``send_formazione_audit_digest`` trimestrale (audit ISO): qui è il
reminder operativo ricorrente.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.notifiche import invia_notifica

from anagrafica.services.email_digest import digest_fragment, scadenza_badge
from anagrafica.services.reminders import get_reminder_recipients

_IN_SCADENZA = ("IN_SCADENZA_30", "IN_SCADENZA_90")


class Command(BaseCommand):
    help = "Digest email dei corsi obbligatori scaduti o in scadenza (+ notifica al dipendente)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=60,
            help="Giorni di anticipo per i corsi in scadenza (default: 60).",
        )
        parser.add_argument(
            "--recipients", nargs="*",
            help="Email destinatari del digest (sovrascrive SiteConfig/ADMINS).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare.")

    def handle(self, *args, **options):
        from anagrafica.models_formazione import TrainingDeadline

        today = timezone.localdate()
        days = max(1, int(options.get("days") or 60))
        dry_run = bool(options.get("dry_run"))
        recipients = get_reminder_recipients("training_reminder_emails", options.get("recipients") or [])

        base = TrainingDeadline.objects.filter(is_required=True).select_related("corso")
        scadute = list(base.filter(stato_scadenza="SCADUTO").order_by("giorni_alla_scadenza"))
        in_scadenza = list(
            base.filter(stato_scadenza__in=_IN_SCADENZA, giorni_alla_scadenza__lte=days,
                        giorni_alla_scadenza__gte=0)
            .order_by("giorni_alla_scadenza")
        )

        if not scadute and not in_scadenza:
            self.stdout.write("Nessun corso obbligatorio scaduto o in scadenza.")
            return

        lines = [
            f"NOVICROM HUB - Promemoria scadenze formazione del {today:%d-%m-%Y}",
            "=" * 60,
            "",
        ]

        if scadute:
            lines.append(f"CORSI SCADUTI ({len(scadute)}):")
            for d in scadute:
                over = abs(d.giorni_alla_scadenza) if d.giorni_alla_scadenza is not None else 0
                lines.append(
                    f"  [{over}gg] dip #{d.legacy_anagrafica_id} - {d.corso.codice} {d.corso.titolo}"
                    + (f" - scaduto il {d.data_scadenza:%d-%m-%Y}" if d.data_scadenza else " - scaduto")
                )
                if not dry_run:
                    invia_notifica(
                        d.legacy_anagrafica_id, "formazione_scadenza",
                        f"Corso obbligatorio scaduto: {d.corso.titolo}"
                        + (f" dal {d.data_scadenza:%d-%m-%Y}." if d.data_scadenza else "."),
                        "/anagrafica/formazione/",
                    )
            lines.append("")

        if in_scadenza:
            lines.append(f"CORSI IN SCADENZA entro {days} giorni ({len(in_scadenza)}):")
            for d in in_scadenza:
                left = d.giorni_alla_scadenza or 0
                lines.append(
                    f"  [{left}gg] dip #{d.legacy_anagrafica_id} - {d.corso.codice} {d.corso.titolo}"
                    + (f" - scadenza {d.data_scadenza:%d-%m-%Y}" if d.data_scadenza else "")
                )
                if not dry_run:
                    invia_notifica(
                        d.legacy_anagrafica_id, "formazione_scadenza",
                        f"Corso obbligatorio in scadenza tra {left} giorni: {d.corso.titolo}.",
                        "/anagrafica/formazione/",
                    )
            lines.append("")

        body = "\n".join(lines)
        subject = (
            f"[FORMAZIONE] {len(scadute)} scaduti + {len(in_scadenza)} in scadenza - {today:%d-%m-%Y}"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna email/notifica inviata."))
            self.stdout.write(f"Destinatari: {recipients}")
            self.stdout.write(body)
            return

        if not recipients:
            self.stdout.write(self.style.ERROR(
                "Nessun destinatario configurato (SiteConfig 'training_reminder_emails' / ADMINS vuoti)."
                " Notifiche in-app inviate comunque."
            ))
            return

        scadute_cards = [{
            "title": f"Dipendente #{d.legacy_anagrafica_id}",
            "subtitle": f"{d.corso.codice} · {d.corso.titolo}",
            "badge": scadenza_badge(
                abs(d.giorni_alla_scadenza) if d.giorni_alla_scadenza is not None else None,
                scaduto=True, label_scaduto="Scaduto"),
            "note": (f"Scaduto il {d.data_scadenza:%d-%m-%Y}" if d.data_scadenza else "Scaduto"),
            "accent": "#dc2626",
        } for d in scadute]
        inscad_cards = [{
            "title": f"Dipendente #{d.legacy_anagrafica_id}",
            "subtitle": f"{d.corso.codice} · {d.corso.titolo}",
            "badge": scadenza_badge(d.giorni_alla_scadenza or 0),
            "note": (f"Scadenza {d.data_scadenza:%d-%m-%Y}" if d.data_scadenza else ""),
            "accent": "#f59e0b",
        } for d in in_scadenza]
        fragment = digest_fragment([
            (f"Corsi scaduti ({len(scadute)})", scadute_cards),
            (f"Corsi in scadenza entro {days} giorni ({len(in_scadenza)})", inscad_cards),
        ])

        from automazioni.mail_config import apply_mail_overrides
        from core.email_utils import send_hub_mail
        subject, body, fragment, footer = apply_mail_overrides(
            "training_expiry_reminders", subject=subject, body_text=body, fragment=fragment)
        send_hub_mail(
            subject, body, recipients,
            email_type="Anagrafica HR",
            section_label="Reminder formazione",
            body_html_fragment=fragment,
            footer_note=footer,
            fail_silently=False,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Email inviata a {len(recipients)} destinatari."
            f" Scaduti={len(scadute)} In_scadenza={len(in_scadenza)}"
        ))
