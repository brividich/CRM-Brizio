r"""Cancella le conversazioni dell'assistente AI scadute (storico chat).

    python django_app\manage.py ai_pulisci_conversazioni            # usa AI_CHAT_HISTORY_RETENTION_DAYS
    python django_app\manage.py ai_pulisci_conversazioni --giorni 30
    python django_app\manage.py ai_pulisci_conversazioni --tutte --conferma
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from ai_assistant.conversazioni import giorni_conservazione, pulisci_scadute
from ai_assistant.models import AiConversation


class Command(BaseCommand):
    help = "Cancella le conversazioni dell'assistente AI ferme da più dei giorni di conservazione."

    def add_arguments(self, parser):
        parser.add_argument("--giorni", type=int, default=None, help="Giorni di conservazione (default da settings).")
        parser.add_argument("--tutte", action="store_true", help="Cancella tutte le conversazioni di tutti gli utenti.")
        parser.add_argument("--conferma", action="store_true", help="Necessario con --tutte.")

    def handle(self, *args, **options):
        if options["tutte"]:
            if not options["conferma"]:
                raise CommandError("--tutte cancella lo storico di tutti gli utenti: aggiungi --conferma.")
            numero = AiConversation.objects.count()
            AiConversation.objects.all().delete()
            self.stdout.write(self.style.SUCCESS(f"Conversazioni cancellate: {numero} (tutte)."))
            return
        giorni = options["giorni"] or giorni_conservazione()
        if giorni < 1:
            raise CommandError("--giorni deve essere almeno 1.")
        numero = pulisci_scadute(giorni=giorni)
        self.stdout.write(self.style.SUCCESS(f"Conversazioni cancellate: {numero} (ferme da più di {giorni} giorni)."))
