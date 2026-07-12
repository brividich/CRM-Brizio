"""Crea/aggiorna la revisione privacy del tool live Contatori MFC (Ondata 6.1).

Il tool runtime ``_contatori_context`` espone SOLO aggregati non personali dei
contatori multifunzione (consumo copie per trimestre, classifica reparti,
ripartizione BN/colore e A4/A3, stato delle rilevazioni); le macchine sono
identificate da reparto e matricola. Il confine reale e' il permesso canonico
ACL v2 ``contatori.dashboard.view`` (gate applicato nel tool).

Questo comando prepara il record ``AiToolPrivacyReview`` di governance con la
matrice campi gia' compilata. Per DEFAULT crea/lascia il record in stato
``pending`` (firma umana di governance); con ``--approve`` lo porta ad
``approved``.

    python manage.py ai_seed_contatori_privacy_review            # prepara (pending)
    python manage.py ai_seed_contatori_privacy_review --approve  # firma governance
    python manage.py ai_seed_contatori_privacy_review --status restricted
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from ai_assistant.models import AiToolPrivacyReview

TOOL_KEY = "contatori_summary"
TOOL_LABEL = "Contatori MFC (consumi/classifica reparti)"
ALLOWED_FIELDS = (
    "reparto, matricola/modello macchina, consumo copie per trimestre (BN/colore), "
    "classifica reparti per volume, quota colore, ripartizione BN/colore e A4/A3, "
    "conteggi stato rilevazioni (aggiornate/da aggiornare/mai), anomalie di monotonia (numero)"
)
BLOCKED_FIELDS = (
    "host/IP SNMP, community SNMP, numeri e importi fattura, note delle letture, "
    "dettaglio nominativo di chi ha registrato le letture"
)
NOTES = (
    "Tool runtime AI su aggregati NON personali dei contatori multifunzione. "
    "Gate ACL canonico contatori.dashboard.view e audit metadata-only applicati nel "
    "tool (_contatori_context). Rischio privacy basso: nessun dato personale."
)
_ACTIVE = ("approved", "restricted")


class Command(BaseCommand):
    help = (
        "Crea/aggiorna la revisione privacy del tool live Contatori MFC "
        "(default: pending; --approve per la firma di governance)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--approve",
            action="store_true",
            help="Imposta privacy_status=approved. Default: pending.",
        )
        parser.add_argument(
            "--status",
            choices=[c[0] for c in AiToolPrivacyReview._meta.get_field("privacy_status").choices],
            help="Stato esplicito (override di --approve).",
        )
        parser.add_argument(
            "--retention-days",
            type=int,
            default=None,
            help="Retention audit per questo tool (vuoto = policy globale).",
        )

    def handle(self, *args, **options):
        wants_status = options.get("status") or ("approved" if options.get("approve") else None)
        review, created = AiToolPrivacyReview.objects.get_or_create(
            tool_key=TOOL_KEY,
            defaults={
                "tool_label": TOOL_LABEL,
                "privacy_status": wants_status or "pending",
                "allowed_fields": ALLOWED_FIELDS,
                "blocked_fields": BLOCKED_FIELDS,
                "retention_days": options.get("retention_days"),
                "notes": NOTES,
            },
        )
        if not created:
            # Idempotente: completa i metadati mancanti, cambia stato solo se richiesto.
            review.tool_label = review.tool_label or TOOL_LABEL
            review.allowed_fields = review.allowed_fields or ALLOWED_FIELDS
            review.blocked_fields = review.blocked_fields or BLOCKED_FIELDS
            review.notes = review.notes or NOTES
            if wants_status:
                review.privacy_status = wants_status
            if options.get("retention_days") is not None:
                review.retention_days = options.get("retention_days")
        if review.privacy_status in _ACTIVE and review.reviewed_at is None:
            review.reviewed_at = timezone.now()
        review.save()

        verbo = "creata" if created else "aggiornata"
        self.stdout.write(self.style.SUCCESS(
            f"Revisione privacy {verbo}: tool_key='{TOOL_KEY}', status='{review.privacy_status}'."
        ))
