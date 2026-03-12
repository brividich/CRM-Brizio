from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import DatabaseError, transaction

from core.legacy_cache import bump_legacy_cache_version
from core.legacy_models import Pulsante


PULSANTI = [
    ("asset_list", "Asset - Lista", "asset_list"),
    ("asset_view", "Asset - Dettaglio", "asset_view"),
    ("asset_detail_layout", "Asset - Configura layout dettaglio", "asset_detail_layout_admin"),
    ("asset_create", "Asset - Nuovo", "asset_create"),
    ("asset_edit", "Asset - Modifica", "asset_edit"),
    ("asset_assign", "Asset - Assegnazione", "asset_assign"),
    ("wo_list", "Asset - Interventi lista", "wo_list"),
    ("wo_view", "Asset - Intervento dettaglio", "wo_view"),
    ("wo_create", "Asset - Intervento nuovo", "wo_create"),
    ("wo_close", "Asset - Intervento chiusura", "wo_close"),
    ("periodic_verifications", "Asset - Verifiche periodiche", "periodic_verifications"),
    ("reports", "Asset - Report", "reports"),
]


def _upsert_pulsante(codice: str, label: str, route_name: str) -> tuple[bool, bool]:
    url_value = f"django:assets:{route_name}"
    created = False
    changed = False
    row = None
    try:
        row = Pulsante.objects.filter(url__iexact=url_value).order_by("-id").first()
        if row is None:
            row = Pulsante.objects.filter(modulo__iexact="assets", codice__iexact=codice).order_by("-id").first()
    except DatabaseError:
        return created, changed

    if row is None:
        try:
            Pulsante.objects.create(
                modulo="assets",
                codice=codice,
                nome_visibile=label,
                url=url_value,
                icona="database",
            )
            return True, True
        except DatabaseError:
            return created, changed

    updates = []
    if (row.modulo or "").strip() != "assets":
        row.modulo = "assets"
        updates.append("modulo")
    if (row.codice or "").strip() != codice:
        row.codice = codice
        updates.append("codice")
    if (row.nome_visibile or "").strip() != label:
        row.nome_visibile = label
        updates.append("nome_visibile")
    if (row.url or "").strip() != url_value:
        row.url = url_value
        updates.append("url")
    if not row.icona:
        row.icona = "database"
        updates.append("icona")

    if updates:
        try:
            row.save(update_fields=updates)
            changed = True
        except DatabaseError:
            return created, False
    return created, changed


class Command(BaseCommand):
    help = "Crea/aggiorna i pulsanti ACL legacy per il modulo assets."

    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0
        try:
            with transaction.atomic():
                for codice, label, route_name in PULSANTI:
                    created, changed = _upsert_pulsante(codice, label, route_name)
                    if created:
                        created_count += 1
                    elif changed:
                        updated_count += 1
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"Errore seed ACL assets: {exc}"))
            return

        if created_count or updated_count:
            try:
                bump_legacy_cache_version()
            except Exception:
                pass

        self.stdout.write(
            self.style.SUCCESS(
                f"Seed ACL assets completato. Creati={created_count}, Aggiornati={updated_count}, Totale={len(PULSANTI)}"
            )
        )
