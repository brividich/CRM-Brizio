from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from core.caporeparto_utils import normalize_caporeparto_option
from core.models import OptioneConfig, RepartoCapoMapping, UserExtraInfo


class Command(BaseCommand):
    help = "Allinea i caporeparto locali agli utenti legacy e promuove il ruolo a caporeparto quando necessario."

    def handle(self, *args, **options):
        updated_options = 0
        updated_mappings = 0
        updated_extra = 0
        skipped = 0

        with transaction.atomic():
            for option in OptioneConfig.objects.filter(tipo__iexact="caporeparto").order_by("id"):
                normalized = normalize_caporeparto_option(
                    option.valore,
                    legacy_user_id=getattr(option, "legacy_user_id", None),
                    promote_role=True,
                )
                if not normalized.get("ok"):
                    skipped += 1
                    continue
                new_value = str(normalized["value"] or "").strip()
                new_user_id = int(normalized["legacy_user_id"])
                fields: list[str] = []
                if option.valore != new_value:
                    option.valore = new_value
                    fields.append("valore")
                if getattr(option, "legacy_user_id", None) != new_user_id:
                    option.legacy_user_id = new_user_id
                    fields.append("legacy_user_id")
                if fields:
                    option.save(update_fields=fields)
                    updated_options += 1

            for mapping in RepartoCapoMapping.objects.filter(is_active=True).order_by("id"):
                normalized = normalize_caporeparto_option(mapping.caporeparto, promote_role=True)
                if not normalized.get("ok"):
                    skipped += 1
                    continue
                new_value = str(normalized["value"] or "").strip()
                if mapping.caporeparto != new_value:
                    mapping.caporeparto = new_value
                    mapping.save(update_fields=["caporeparto"])
                    updated_mappings += 1

            for extra in UserExtraInfo.objects.exclude(caporeparto="").order_by("id"):
                normalized = normalize_caporeparto_option(extra.caporeparto, promote_role=True)
                if not normalized.get("ok"):
                    skipped += 1
                    continue
                new_value = str(normalized["value"] or "").strip()
                if extra.caporeparto != new_value:
                    extra.caporeparto = new_value
                    extra.save(update_fields=["caporeparto"])
                    updated_extra += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Sync completato: "
                f"opzioni aggiornate={updated_options}, "
                f"mapping aggiornati={updated_mappings}, "
                f"user extra aggiornati={updated_extra}, "
                f"skipped={skipped}."
            )
        )
