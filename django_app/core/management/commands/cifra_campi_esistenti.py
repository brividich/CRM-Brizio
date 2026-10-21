"""Cifra i valori in chiaro dei campi ``CampoCifrato`` (GDPR, checklist E4).

I campi passati a ``CampoCifrato`` si cifrano a ogni salvataggio; questo comando
cifra subito i valori gia' presenti. ``--ruota`` ricifra anche i valori gia'
cifrati con la chiave corrente (dopo un cambio di ``DOCUMENT_ENCRYPTION_KEY``,
con la vecchia in ``DOCUMENT_ENCRYPTION_OLD_KEYS``).

Uso:
    python manage.py cifra_campi_esistenti            # anteprima: quanti valori in chiaro
    python manage.py cifra_campi_esistenti --apply
    python manage.py cifra_campi_esistenti --apply --ruota
"""
from __future__ import annotations

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.campi_cifrati import PREFISSO, CampoCifrato


def campi_cifrati():
    for model in apps.get_models():
        for field in model._meta.concrete_fields:
            if isinstance(field, CampoCifrato):
                yield model, field


class Command(BaseCommand):
    help = "Cifra i valori in chiaro dei campi cifrati (anteprima senza --apply)"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--ruota", action="store_true", help="Ricifra anche i valori gia' cifrati.")

    def handle(self, *args, **options):
        apply = options["apply"]
        if apply and not str(getattr(settings, "DOCUMENT_ENCRYPTION_KEY", "") or "").strip():
            raise CommandError("DOCUMENT_ENCRYPTION_KEY non configurata: i valori resterebbero in chiaro.")
        totale = 0
        for model, field in campi_cifrati():
            qs = model._default_manager.exclude(**{field.name: ""}).exclude(**{f"{field.name}__isnull": True})
            if not options["ruota"]:
                qs = qs.exclude(**{f"{field.name}__startswith": PREFISSO})
            ids = list(qs.values_list("pk", flat=True))
            totale += len(ids)
            if apply:
                for pk in ids:
                    valore = model._default_manager.filter(pk=pk).values_list(field.name, flat=True).first()
                    if valore:
                        model._default_manager.filter(pk=pk).update(**{field.name: valore})
            self.stdout.write(f"{'[cifrati]' if apply else '[anteprima]'} {model._meta.label}.{field.name}: {len(ids)}")
        if apply:
            from core.audit import log_action

            log_action(None, "cifra_campi_esistenti", "core", {"valori": totale, "ruota": bool(options["ruota"])})
        else:
            self.stdout.write(f"Anteprima: {totale} valori da cifrare. Rilancia con --apply.")
