"""Copia nel registro Automazioni → «Mail inviate» le mail anomalie partite prima
che il modulo scrivesse direttamente nel registro.

La fonte è il log del modulo (``AnomalieEmailLog``): destinatari, copia, oggetto,
esito, errore, OP e data originale. Del testo non si copia nulla.

- Solo dentro la finestra di retention del registro (stessi giorni dei run log):
  le righe più vecchie le cancellerebbe subito ``cleanup_run_logs``.
- Solo prima della prima riga anomalie già scritta dal portale: quelle successive
  sono già nel registro.
- Rilanciabile: una riga con stesso tipo, oggetto e data esatta non si ricopia.

Dry-run di default, ``--apply`` per scrivere.

    python manage.py recupera_mail_inviate_anomalie
    python manage.py recupera_mail_inviate_anomalie --apply
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = "Recupera nel registro «Mail inviate» le mail anomalie precedenti (dal Log attività del modulo)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", default=False,
                            help="Scrive davvero. Senza questo flag è dry-run.")
        parser.add_argument("--days", type=int, default=None,
                            help="Giorni da recuperare (default: retention del registro).")

    def handle(self, *args, **options):
        from automazioni.mail_inviate import _elenco
        from automazioni.models import EmailInviata
        from automazioni.runlog_retention import get_retention_days

        from anomalie.mail_log_models import AnomalieEmailLog

        apply = bool(options.get("apply"))
        days = options.get("days")
        days = int(days) if days is not None else get_retention_days()
        dal = timezone.now() - timedelta(days=days)

        prima_live = (
            EmailInviata.objects.filter(origine__startswith="anomalie_")
            .order_by("inviata_il").values_list("inviata_il", flat=True).first()
        )
        qs = AnomalieEmailLog.objects.filter(created_at__gte=dal).order_by("created_at", "id")
        if prima_live:
            qs = qs.filter(created_at__lt=prima_live)

        gia = set(
            EmailInviata.objects.filter(origine__startswith="anomalie_", inviata_il__gte=dal)
            .values_list("origine", "oggetto", "inviata_il")
        )

        nuove = []
        saltate = 0
        for log in qs.iterator():
            origine = f"anomalie_{log.kind or 'altro'}"[:40]
            oggetto = (log.subject or "")[:255]
            if (origine, oggetto, log.created_at) in gia:
                saltate += 1
                continue
            fallita = log.status == AnomalieEmailLog.Status.FAILED
            nuove.append(EmailInviata(
                inviata_il=log.created_at,
                origine=origine,
                sorgente="OP" if log.op_id else "",
                record_id=(log.op_id or "")[:60],
                destinatari=_elenco(log.to_emails or []),
                copia=_elenco(log.cc_emails or []),
                oggetto=oggetto,
                esito=EmailInviata.ESITO_ERRORE if fallita else EmailInviata.ESITO_INVIATA,
                errore=((log.error or "Invio non riuscito") if fallita else "")[:2000],
            ))

        mode = "[apply]" if apply else "[dry-run]"
        limite = f", prima del {timezone.localtime(prima_live):%d/%m/%Y %H:%M}" if prima_live else ""
        self.stdout.write(
            f"{mode} Mail anomalie dal {timezone.localtime(dal):%d/%m/%Y}{limite}: "
            f"da copiare {len(nuove)}, già presenti {saltate}."
        )
        if not nuove:
            return
        if not apply:
            self.stdout.write("Esegui con --apply per scriverle nel registro.")
            return
        # Una create per riga: su SQL Server il bulk_create a batch rompe i savepoint.
        with transaction.atomic():
            for riga in nuove:
                riga.save()
        self.stdout.write(self.style.SUCCESS(f"Copiate {len(nuove)} mail nel registro «Mail inviate»."))
