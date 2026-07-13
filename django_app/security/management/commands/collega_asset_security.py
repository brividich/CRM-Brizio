"""Collega i SecurityAsset agli Asset dell'HUB.

Criterio: `ip_address` ↔ `AssetEndpoint.ip`, in fallback `hostname` ↔ `Asset.name`
(match esatto case-insensitive). **Dry-run di default**; `--apply` scrive la FK
`SecurityAsset.hub_asset`. NON modifica mai gli Asset (solo lettura su assets).
"""
from django.core.management.base import BaseCommand

from security.models import SecurityAsset


class Command(BaseCommand):
    help = (
        "Collega SecurityAsset↔Asset (ip_address↔AssetEndpoint.ip, hostname↔Asset.name). "
        "Dry-run salvo --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Scrive la FK SecurityAsset.hub_asset (default: simulazione).")
        parser.add_argument("--ricollega", action="store_true",
                            help="Considera anche i SecurityAsset gia' collegati.")

    def handle(self, *args, **opts):
        from assets.models import Asset  # import lazy: app dell'HUB

        apply = opts["apply"]
        qs = SecurityAsset.objects.all()
        if not opts["ricollega"]:
            qs = qs.filter(hub_asset__isnull=True)

        collegati = ambigui = non_trovati = 0
        for sa in qs:
            match, motivo = None, ""
            if sa.ip_address:
                cand = list(Asset.objects.filter(endpoints__ip=str(sa.ip_address)).distinct())
                if len(cand) == 1:
                    match, motivo = cand[0], "ip↔endpoint"
                elif len(cand) > 1:
                    ambigui += 1
                    self.stdout.write(self.style.WARNING(
                        f"AMBIGUO ip per «{sa.hostname}»: {len(cand)} asset con ip={sa.ip_address}"))
                    continue
            if match is None and sa.hostname:
                cand = list(Asset.objects.filter(name__iexact=sa.hostname.strip()))
                if len(cand) == 1:
                    match, motivo = cand[0], "hostname↔name"
                elif len(cand) > 1:
                    ambigui += 1
                    self.stdout.write(self.style.WARNING(
                        f"AMBIGUO nome per «{sa.hostname}»: {len(cand)} asset con name={sa.hostname}"))
                    continue
            if match is None:
                non_trovati += 1
                continue
            collegati += 1
            self.stdout.write(
                f"{'COLLEGO' if apply else 'MATCH  '} «{sa.hostname}» -> Asset «{match.name}» "
                f"[{match.asset_tag}] ({motivo})")
            if apply:
                sa.hub_asset = match
                sa.save(update_fields=["hub_asset"])

        verbo = "collegati" if apply else "match trovati"
        suffix = "" if apply else "  [DRY-RUN: usa --apply per scrivere]"
        self.stdout.write(self.style.SUCCESS(
            f"\n{collegati} {verbo}, {ambigui} ambigui (saltati), "
            f"{non_trovati} senza corrispondenza.{suffix}"))
