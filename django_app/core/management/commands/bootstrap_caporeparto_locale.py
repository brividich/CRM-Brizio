from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from core.caporeparto_utils import normalize_caporeparto_option
from core.legacy_utils import legacy_table_columns
from core.models import OptioneConfig, RepartoCapoMapping


class Command(BaseCommand):
    help = "Bootstrap delle opzioni locali reparto/caporeparto dalla tabella legacy capi_reparto."

    def handle(self, *args, **options):
        if "title" not in legacy_table_columns("capi_reparto"):
            raise CommandError("Tabella legacy 'capi_reparto' non disponibile o senza colonna 'title'.")

        email_col = "indirizzo_email" if "indirizzo_email" in legacy_table_columns("capi_reparto") else None
        select_cols = ["title"]
        if email_col:
            select_cols.append(email_col)

        with connections["default"].cursor() as cursor:
            cursor.execute(f"SELECT {', '.join(select_cols)} FROM capi_reparto ORDER BY title, id")
            rows = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]

        if not rows:
            self.stdout.write(self.style.WARNING("Nessun record trovato in capi_reparto."))
            return

        reparto_values: list[str] = []
        caporeparto_values: list[str] = []
        reparto_to_capi: dict[str, set[str]] = defaultdict(set)
        seen_reparti: set[str] = set()
        seen_capi: set[str] = set()

        for row in rows:
            reparto = str(row.get("title") or "").strip()
            email = str(row.get(email_col) or "").strip() if email_col else ""
            caporeparto = email or reparto
            if reparto and reparto.casefold() not in seen_reparti:
                seen_reparti.add(reparto.casefold())
                reparto_values.append(reparto)
            if caporeparto and caporeparto.casefold() not in seen_capi:
                seen_capi.add(caporeparto.casefold())
                caporeparto_values.append(caporeparto)
            if reparto and caporeparto:
                reparto_to_capi[reparto].add(caporeparto)

        created_reparti = 0
        created_capi = 0
        created_mappings = 0
        updated_mappings = 0
        skipped_mappings: list[str] = []

        with transaction.atomic():
            for idx, reparto in enumerate(reparto_values, start=1):
                obj, created = OptioneConfig.objects.update_or_create(
                    tipo="reparto",
                    valore=reparto,
                    defaults={"ordine": idx * 10, "is_active": True},
                )
                if created:
                    created_reparti += 1
                elif not obj.is_active:
                    obj.is_active = True
                    obj.save(update_fields=["is_active"])

            for idx, caporeparto in enumerate(caporeparto_values, start=1):
                normalized = normalize_caporeparto_option(caporeparto, promote_role=True)
                if normalized.get("ok"):
                    caporeparto = str(normalized["value"] or "").strip() or caporeparto
                    legacy_user_id = int(normalized["legacy_user_id"])
                else:
                    legacy_user_id = None
                obj, created = OptioneConfig.objects.update_or_create(
                    tipo="caporeparto",
                    valore=caporeparto,
                    defaults={"ordine": idx * 10, "is_active": True, "legacy_user_id": legacy_user_id},
                )
                if created:
                    created_capi += 1
                else:
                    update_fields: list[str] = []
                    if not obj.is_active:
                        obj.is_active = True
                        update_fields.append("is_active")
                    if getattr(obj, "legacy_user_id", None) != legacy_user_id:
                        obj.legacy_user_id = legacy_user_id
                        update_fields.append("legacy_user_id")
                    if update_fields:
                        obj.save(update_fields=update_fields)

            for reparto, capi in reparto_to_capi.items():
                if len(capi) != 1:
                    skipped_mappings.append(f"{reparto}: {', '.join(sorted(capi))}")
                    continue
                caporeparto = next(iter(capi))
                obj, created = RepartoCapoMapping.objects.update_or_create(
                    reparto=reparto,
                    defaults={"caporeparto": caporeparto, "is_active": True},
                )
                if created:
                    created_mappings += 1
                else:
                    updated_mappings += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Bootstrap completato: "
                f"reparti nuovi={created_reparti}, "
                f"caporeparto nuovi={created_capi}, "
                f"mapping creati={created_mappings}, "
                f"mapping aggiornati={updated_mappings}."
            )
        )
        if skipped_mappings:
            self.stdout.write(self.style.WARNING("Mapping reparto -> caporeparto non importati per ambiguità:"))
            for item in skipped_mappings:
                self.stdout.write(f" - {item}")
