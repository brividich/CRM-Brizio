from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import DatabaseError

from attrezzature.acl_bootstrap import bootstrap_attrezzature_acl_endpoints


class Command(BaseCommand):
    help = "Create or update ACL, legacy buttons and Navigation Registry v2 item for Gestione Attrezzatura."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-default-grants",
            action="store_true",
            help="Crea pulsanti, permission e binding senza applicare i grant ruolo di default.",
        )

    def handle(self, *args, **options):
        seed_role_grants = not bool(options.get("no_default_grants"))
        bootstrap_attrezzature_acl_endpoints(force=True, seed_role_grants=seed_role_grants)

        try:
            from core.models import NavigationItem
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"Navigation Registry non disponibile: {exc}"))
            return
        try:
            item, created = NavigationItem.objects.update_or_create(
                code="gestione-attrezzatura",
                defaults={
                    "label": "Gestione Attrezzatura",
                    "route_name": "attrezzature:list",
                    "url_path": "",
                    "section": "topbar",
                    "required_permission_code": "attrezzature.attrezzature.view",
                    "order": 55,
                    "is_visible": True,
                    "is_enabled": True,
                    "icon": "wrench",
                    "description": "Modulo operativo per avanzamento attrezzature e import Excel legacy.",
                },
            )
        except DatabaseError as exc:
            self.stdout.write(self.style.WARNING(f"NavigationItem non creato: {exc}"))
            return
        verb = "Creato" if created else "Aggiornato"
        self.stdout.write(self.style.SUCCESS(f"{verb} NavigationItem {item.code} -> attrezzature:list"))
        if seed_role_grants:
            self.stdout.write(self.style.SUCCESS("Permessi, pulsanti e accessi ruolo default creati/aggiornati."))
        else:
            self.stdout.write(self.style.SUCCESS("Permessi e pulsanti creati/aggiornati senza grant ruolo default."))
