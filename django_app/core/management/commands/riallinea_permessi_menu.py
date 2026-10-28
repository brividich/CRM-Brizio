"""Toglie dalle voci di menu i permission code che non proteggono nessuna pagina.

Sono residui del vecchio menu (``legacy.*`` scritti da «Bootstrap da legacy»):
la matrice dei ruoli non li concede mai, quindi con «Ruoli e permessi» attivo
la voce sparirebbe a chi apre la pagina. Il registro li ignora gia'; questo
comando li toglie dal database, cosi' il Navigation Builder mostra il vero.

Senza ``--apply`` elenca e basta. Tocca solo ``required_permission_code``
(campo di codice, vedi ``NavigationItem``): label, ordine e visibilita' restano.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import NavigationItem
from core.navigation_registry import (
    PERMESSO_ESPLICITO_IGNORATO,
    bump_navigation_registry_version,
    describe_navigation_items_permission,
)


class Command(BaseCommand):
    help = "Toglie dalle voci di menu i permission code che non proteggono nessuna pagina (dry-run senza --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Scrive le modifiche (default: solo elenco).")

    def handle(self, *args, **options):
        items = list(NavigationItem.objects.exclude(required_permission_code="").order_by("section", "order", "id"))
        info_map = describe_navigation_items_permission(items)
        da_togliere = [item for item in items if info_map[int(item.id)]["stato"] == PERMESSO_ESPLICITO_IGNORATO]

        for item in da_togliere:
            info = info_map[int(item.id)]
            self.stdout.write(
                f"{item.section:<12} {item.code:<40} {info['explicit']} -> pagina {info['target']}"
            )
        self.stdout.write(f"Voci con permesso vecchio: {len(da_togliere)} su {len(items)} con permission code.")

        if not options["apply"]:
            self.stdout.write("Dry-run: nessuna modifica. Rilancia con --apply per scriverle.")
            return
        if not da_togliere:
            return
        with transaction.atomic():
            NavigationItem.objects.filter(id__in=[int(i.id) for i in da_togliere]).update(required_permission_code="")
            transaction.on_commit(bump_navigation_registry_version)
        self.stdout.write(self.style.SUCCESS(f"Tolti {len(da_togliere)} permission code: decide il permesso della pagina."))
