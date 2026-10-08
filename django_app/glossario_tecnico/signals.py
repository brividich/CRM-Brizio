"""Ogni modifica a termini o varianti invalida la regex del glossario e l'indice RAG."""

from __future__ import annotations

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Termine, Variante


@receiver([post_save, post_delete], sender=Termine)
@receiver([post_save, post_delete], sender=Variante)
def invalida_glossario_rag(sender, **kwargs):
    try:
        from ai_assistant.glossario_rag import bump_versione

        bump_versione()
    except Exception:
        pass
