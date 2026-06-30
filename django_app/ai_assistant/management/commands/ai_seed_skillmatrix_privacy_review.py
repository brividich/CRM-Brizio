"""Crea/aggiorna la revisione privacy del tool live Skill Matrix (MOD.187).

Il tool runtime ``_skillmatrix_context`` e' SAFE-BY-DEFAULT: non espone alcun dato
finche' non esiste una ``AiToolPrivacyReview`` con stato attivo (approved/restricted)
per ``tool_key='skill_matrix'``. Questo comando prepara quel record con la matrice
campi (consentiti/vietati) gia' compilata.

Per DEFAULT crea/lascia il record in stato ``pending`` (decisione umana di governance:
il tool resta inerte). Con ``--approve`` lo porta ad ``approved`` e ACCENDE il tool
(che esporra' dati ai soli utenti con il permesso ``anagrafica.skillmatrix.view``).

    python manage.py ai_seed_skillmatrix_privacy_review            # prepara (pending)
    python manage.py ai_seed_skillmatrix_privacy_review --approve  # attiva
    python manage.py ai_seed_skillmatrix_privacy_review --status restricted
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from ai_assistant.models import AiToolPrivacyReview

TOOL_KEY = "skill_matrix"
TOOL_LABEL = "Skill Matrix (abilitazioni macchina MOD.187)"
ALLOWED_FIELDS = (
    "nome operatore, livello (I/L/U/O), macchina/asset, stato (attiva/sospesa), "
    "operativo, prossima revisione, KPI aggregati (prontezza, macchine scoperte, uomo-solo)"
)
BLOCKED_FIELDS = (
    "note, codice fiscale, dati sanitari/idoneita', retribuzioni, contatti, "
    "documenti/allegati, percorsi file"
)
NOTES = (
    "Tool runtime AI che espone abilitazioni macchina = dato personale dei dipendenti. "
    "Minimizzazione campi, ACL canonico anagrafica.skillmatrix.view e audit metadata-only "
    "sono applicati nel tool (_skillmatrix_context)."
)
_ACTIVE = ("approved", "restricted")


class Command(BaseCommand):
    help = (
        "Crea/aggiorna la revisione privacy del tool live Skill Matrix "
        "(default: pending/inerte; --approve per attivarlo)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--approve",
            action="store_true",
            help="Imposta privacy_status=approved e ACCENDE il tool. Default: pending.",
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
            # Idempotente: completa i metadati mancanti, cambia stato solo se richiesto esplicitamente.
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
        if review.privacy_status in _ACTIVE:
            self.stdout.write(
                "Tool Skill Matrix ATTIVO: esporra' dati ai soli utenti con 'anagrafica.skillmatrix.view'."
            )
        else:
            self.stdout.write(
                "Stato non attivo: il tool resta inerte (nessun dato). Rilancia con --approve per attivarlo."
            )
