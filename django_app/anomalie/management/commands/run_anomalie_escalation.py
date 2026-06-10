"""Promemoria + escalation anomalie 'OP da controllare'.

Utilizzo:
    python manage.py run_anomalie_escalation                 # reminder + email se in finestra
    python manage.py run_anomalie_escalation --dry-run       # mostra OP da controllare, no scrittura
    python manage.py run_anomalie_escalation --force-email    # invia il resoconto a prescindere
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Promemoria dashboard + resoconto email per gli OP con anomalie 'In attesa' da controllare."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra gli OP da controllare senza creare notifiche né inviare email.",
        )
        parser.add_argument(
            "--force-email",
            action="store_true",
            help="Invia il resoconto email a prescindere da giorno/ora/attivazione.",
        )

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        force_email = bool(options.get("force_email"))

        from anomalie.escalation_config import get_escalation_config
        from anomalie.mail_action_service import _fetch_op_da_controllare

        cfg = get_escalation_config()
        soglia = int(cfg["soglia_ore"])

        if dry_run:
            op_rows = _fetch_op_da_controllare(soglia)
            over = [op for op in op_rows if op.get("over_threshold")]
            self.stdout.write(
                f"[dry-run] attivo={cfg['attivo']} soglia={soglia}h ora_invio={cfg['ora_invio']} "
                f"giorni={cfg['cadenza_label']}"
            )
            self.stdout.write(f"[dry-run] OP da controllare: {len(op_rows)} (oltre soglia: {len(over)})")
            for op in op_rows:
                flag = " ⚠ OLTRE SOGLIA" if op.get("over_threshold") else ""
                pn = f" P/N {op['pn']}" if op.get("pn") else ""
                self.stdout.write(
                    f"  • OP {op['op_id']}{pn} — {op['n_anomalie']} anomalie · ferma da {int(op.get('ore_max') or 0)}h{flag}"
                )
            return

        from anomalie.tasks import run_anomalie_escalation

        result = run_anomalie_escalation(force_email=force_email)
        self.stdout.write(
            self.style.SUCCESS(
                f"Promemoria creati: {result['reminders']} · email inviata: {result['email_sent']} · "
                f"OP da controllare: {result['op_da_controllare']} (oltre soglia: {result['op_over']})"
            )
        )
