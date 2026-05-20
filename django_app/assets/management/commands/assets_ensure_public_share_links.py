from __future__ import annotations

import os
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from assets.models import Asset
from assets.services.sharepoint_public_links import (
    ensure_asset_public_share_link,
    resolve_asset_drive_item_ids,
    validate_asset_inside_allowed_root,
)


def _public_links_feature_enabled() -> bool:
    value = os.getenv("SHAREPOINT_ASSET_PUBLIC_LINKS_ENABLED")
    if value is None:
        return bool(getattr(settings, "SHAREPOINT_ASSET_PUBLIC_LINKS_ENABLED", False))
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Command(BaseCommand):
    help = "Genera link pubblici Graph read-only per cartelle asset sotto ASSET CN."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Simula senza salvare nulla (default).")
        mode.add_argument("--apply", action="store_true", help="Crea/salva i link pubblici.")
        parser.add_argument("--force", action="store_true", help="Rigenera/verifica anche se il link pubblico esiste.")
        parser.add_argument("--only-missing", action="store_true", help="Lavora solo sugli asset senza sharepoint_public_url.")
        parser.add_argument("--asset-tag", type=str, default="", help="Limita a un singolo asset_tag.")

    def handle(self, *args, **options):
        apply = bool(options["apply"])
        force = bool(options["force"])
        only_missing = bool(options["only_missing"])
        asset_tag = (options.get("asset_tag") or "").strip()

        queryset = Asset.objects.exclude(sharepoint_folder_path="").order_by("asset_tag", "id")
        if asset_tag:
            queryset = queryset.filter(asset_tag=asset_tag)
        if asset_tag and not queryset.exists():
            raise CommandError(f"Asset non trovato o non selezionabile: {asset_tag}")

        mode = "APPLY" if apply else "DRY-RUN"
        self.stdout.write(f"Link pubblici SharePoint asset | modalita: {mode}")

        counters = {
            "scanned": 0,
            "eligible": 0,
            "created": 0,
            "existing": 0,
            "skipped_not_in_asset_cn": 0,
            "skipped_missing_drive_item": 0,
            "skipped_feature_disabled": 0,
            "errors": 0,
        }

        for asset in queryset.iterator():
            counters["scanned"] += 1
            row = {
                "asset_tag": asset.asset_tag,
                "nome": asset.name,
                "status": "",
                "public_url_created": "no",
                "public_url_existing": "si" if asset.sharepoint_public_url else "no",
                "skipped": "no",
                "error": "",
            }

            if not _public_links_feature_enabled():
                counters["skipped_feature_disabled"] += 1
                row.update(status="feature_disabled", skipped="si", error="Feature disattivata.")
                self._write_row(row)
                continue

            if asset.sharepoint_public_url and only_missing:
                counters["existing"] += 1
                row.update(status="existing_only_missing", skipped="si", public_url_existing="si")
                self._write_row(row)
                continue

            if asset.sharepoint_public_url and not force:
                counters["existing"] += 1
                row.update(status="existing")
                self._write_row(row)
                continue

            try:
                if not asset.sharepoint_drive_id or not asset.sharepoint_item_id:
                    resolved = resolve_asset_drive_item_ids(asset, save=apply)
                    if not resolved.get("ok"):
                        status = resolved.get("status")
                        if status == "not_in_asset_cn":
                            counters["skipped_not_in_asset_cn"] += 1
                        else:
                            counters["skipped_missing_drive_item"] += 1
                        row.update(status=status or "missing_drive_item", skipped="si", error=resolved.get("error", ""))
                        self._write_row(row)
                        continue
                    asset.sharepoint_drive_id = resolved["drive_id"]
                    asset.sharepoint_item_id = resolved["item_id"]

                validation = validate_asset_inside_allowed_root(asset)
                if not validation.get("ok"):
                    status = validation.get("status")
                    if status == "missing_drive_item":
                        counters["skipped_missing_drive_item"] += 1
                    elif status == "not_in_asset_cn":
                        counters["skipped_not_in_asset_cn"] += 1
                    else:
                        counters["errors"] += 1
                    row.update(status=status or "error", skipped="si", error=validation.get("error", ""))
                    self._write_row(row)
                    continue

                counters["eligible"] += 1
                if not apply:
                    row.update(status="eligible_dry_run", skipped="si")
                    self._write_row(row)
                    continue

                result = ensure_asset_public_share_link(asset, save=True, force=force)
                if result.get("ok") and result.get("status") == "existing":
                    counters["existing"] += 1
                    row.update(status="existing", public_url_existing="si")
                elif result.get("ok"):
                    counters["created"] += 1
                    row.update(status="created", public_url_created="si")
                else:
                    status = result.get("status") or "error"
                    if status == "feature_disabled":
                        counters["skipped_feature_disabled"] += 1
                    elif status == "missing_drive_item":
                        counters["skipped_missing_drive_item"] += 1
                    elif status == "not_in_asset_cn":
                        counters["skipped_not_in_asset_cn"] += 1
                    else:
                        counters["errors"] += 1
                    row.update(status=status, skipped="si", error=result.get("error", ""))
                self._write_row(row)
            except Exception as exc:
                counters["errors"] += 1
                row.update(status="error", skipped="si", error=str(exc))
                self._write_row(row)

        self.stdout.write("Riepilogo:")
        for key in (
            "scanned",
            "eligible",
            "created",
            "existing",
            "skipped_not_in_asset_cn",
            "skipped_missing_drive_item",
            "skipped_feature_disabled",
            "errors",
        ):
            self.stdout.write(f"- {key}: {counters[key]}")

    def _write_row(self, row: dict[str, str]) -> None:
        self.stdout.write(
            " | ".join(
                [
                    f"asset_tag={row['asset_tag']}",
                    f"nome={row['nome']}",
                    f"status={row['status']}",
                    f"public_url_created={row['public_url_created']}",
                    f"public_url_existing={row['public_url_existing']}",
                    f"skipped={row['skipped']}",
                    f"error={row['error']}",
                ]
            )
        )
