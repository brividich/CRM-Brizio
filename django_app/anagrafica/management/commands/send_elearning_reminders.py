"""Promemoria micro-corsi e-learning ancora da completare.

Per ogni iscrizione e-learning non completata (ISCRITTO/IN_CORSO/NON_SUPERATO su
corso attivo) invia una notifica in-app al discente e produce un digest email per
i responsabili formazione. Pattern speculare a ``send_visite_expiry_reminders`` /
``send_visite_mediche_digest``. Schedulare via QCluster (intervalli in MINUTI).

Destinatari digest: override CLI → SiteConfig ``elearning_reminder_emails`` →
ADMINS → superuser. Notifica in-app sempre al discente (rispetta gli interruttori).
"""
from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.utils import timezone

from anagrafica.services.elearning_notifications import (
    iter_corsi_da_completare,
    notify_promemoria_da_completare,
)
from anagrafica.services.email_digest import digest_fragment
from anagrafica.services.reminders import get_reminder_recipients

_STATO_LABEL = {"ISCRITTO": "Iscritto", "IN_CORSO": "In corso", "NON_SUPERATO": "Non superato"}


class Command(BaseCommand):
    help = "Promemoria e digest dei micro-corsi e-learning non ancora completati."

    def add_arguments(self, parser):
        parser.add_argument(
            "--recipients", nargs="*",
            help="Email destinatari del digest (sovrascrive SiteConfig/ADMINS).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare.")

    def handle(self, *args, **options):
        today = timezone.localdate()
        dry_run = bool(options.get("dry_run"))
        recipients = get_reminder_recipients("elearning_reminder_emails", options.get("recipients") or [])

        iscrizioni = list(iter_corsi_da_completare())
        if not iscrizioni:
            self.stdout.write("Nessun micro-corso e-learning da completare.")
            return

        per_corso: dict[str, list] = defaultdict(list)
        lines = [
            f"NOVICROM HUB - Promemoria micro-corsi e-learning del {today:%d-%m-%Y}",
            "=" * 60,
            "",
            f"Iscrizioni ancora da completare: {len(iscrizioni)}",
            "",
        ]
        for iscr in iscrizioni:
            per_corso[iscr.corso.titolo].append(iscr)
            lines.append(
                f"  [{_STATO_LABEL.get(iscr.stato, iscr.stato)}] dip #{iscr.legacy_anagrafica_id}"
                f" - {iscr.corso.codice} {iscr.corso.titolo}"
            )
            if not dry_run:
                notify_promemoria_da_completare(iscr.corso_id, iscr.legacy_anagrafica_id)

        body = "\n".join(lines)
        subject = f"[E-LEARNING] {len(iscrizioni)} corsi da completare - {today:%d-%m-%Y}"

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna email/notifica inviata."))
            self.stdout.write(f"Destinatari: {recipients}")
            self.stdout.write(body)
            return

        if not recipients:
            self.stdout.write(self.style.ERROR(
                "Nessun destinatario configurato (SiteConfig 'elearning_reminder_emails' / ADMINS vuoti)."
                " Notifiche in-app inviate comunque."
            ))
            return

        sezioni = []
        for titolo, iscr_list in sorted(per_corso.items()):
            cards = [{
                "title": f"Dipendente #{iscr.legacy_anagrafica_id}",
                "subtitle": f"{iscr.corso.codice} · {_STATO_LABEL.get(iscr.stato, iscr.stato)}",
                "note": (f"Avanzamento slide {iscr.ultima_slide_ordine}/{iscr.n_slide_totali}"
                         if iscr.n_slide_totali else ""),
                "accent": "#2563eb",
            } for iscr in iscr_list]
            sezioni.append((f"{titolo} ({len(iscr_list)})", cards))
        fragment = digest_fragment(sezioni)

        from core.email_utils import send_hub_mail
        send_hub_mail(
            subject, body, recipients,
            email_type="Anagrafica HR",
            section_label="Reminder e-learning",
            body_html_fragment=fragment,
            fail_silently=False,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Email inviata a {len(recipients)} destinatari. Iscrizioni da completare: {len(iscrizioni)}."
        ))
