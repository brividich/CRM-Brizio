"""Management command: mpq_propaga_timbri

Propaga lo stato delle abilitazioni MOD.128 ai timbri fisici collegati:
- **sospende** i timbri di abilitazioni non più operative (revocate/sospese/
  dismesse o processo scaduto) — MT CN 06 §10.3;
- **riattiva** le sole auto-sospensioni quando l'abilitazione torna operativa;
- **notifica MSM/Qualità** dei timbri appena sospesi (digest email).

Idempotente. Pensato per essere schedulato (django-q, accanto al report au12
``report_scadenze_settimanale``), oppure eseguito a mano.

Utilizzo:
    python manage.py mpq_propaga_timbri
    python manage.py mpq_propaga_timbri --dry-run
    python manage.py mpq_propaga_timbri --no-notify
    python manage.py mpq_propaga_timbri --emails qualita@azienda.it
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from anagrafica.services.mpq_timbri import notifica_msm_sospensioni, propaga_sospensioni


class Command(BaseCommand):
    help = "Propaga lo stato abilitazioni MOD.128 ai timbri collegati (sospende/riattiva) e notifica MSM."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true",
                            help="Calcola il piano senza scrivere né notificare.")
        parser.add_argument("--no-notify", action="store_true",
                            help="Applica le sospensioni ma non invia la notifica MSM.")
        parser.add_argument("--emails", nargs="*", default=None,
                            help="Override dei destinatari della notifica MSM.")

    def handle(self, *args, **opts):
        dry_run = bool(opts.get("dry_run"))
        stats = propaga_sospensioni(apply=not dry_run)

        self.stdout.write(
            f"{'[DRY-RUN] ' if dry_run else ''}"
            f"Timbri sospesi: {stats['sospesi']} · riattivati: {stats['riattivati']}"
        )

        inviate = 0
        if not dry_run and not opts.get("no_notify") and stats["nuovi_sospesi"]:
            inviate = notifica_msm_sospensioni(
                stats["nuovi_sospesi"], override=opts.get("emails"),
            )
            self.stdout.write(f"Notifica MSM inviata a {inviate} destinatario/i.")

        return None
