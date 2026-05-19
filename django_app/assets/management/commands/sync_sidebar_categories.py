"""Rigenera i gruppi sidebar asset dall'albero delle categorie.

La sidebar asset ha un gruppo per ogni categoria radice e una voce per ogni
sotto-categoria. Quando aggiungi, rinomini, riordini o disattivi categorie
nell'admin, esegui questo command per riallineare la sidebar.

Idempotente: ricostruisce solo i pulsanti categoria, senza toccare gli altri
(Cruscotto, strumenti, Operativita).

Uso:
    python manage.py sync_sidebar_categories
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from assets.models import AssetCategory, AssetSidebarButton
from assets.services.sidebar_categories import rebuild_category_sidebar


class Command(BaseCommand):
    help = "Rigenera i gruppi sidebar asset dall'albero delle categorie."

    def handle(self, *args, **options):
        groups, items = rebuild_category_sidebar(AssetCategory, AssetSidebarButton)
        self.stdout.write(
            self.style.SUCCESS(
                f"Sidebar categorie rigenerata: {groups} gruppi (categorie radice), "
                f"{items} voci (sotto-categorie)."
            )
        )
