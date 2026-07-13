"""Collega le Macchine (contatori) agli Asset dell'HUB.

Criterio: `matricola` ↔ `Asset.serial_number` (match esatto case-insensitive), in
fallback `host` ↔ `AssetEndpoint.ip`. **Dry-run di default**; usa `--apply` per
scrivere la FK `Macchina.asset`. NON modifica mai gli Asset (solo lettura su assets).
"""
from django.core.management.base import BaseCommand

from contatori.models import Macchina


class Command(BaseCommand):
    help = (
        "Collega Macchine↔Asset (matricola↔serial_number, poi host↔AssetEndpoint.ip). "
        "Dry-run salvo --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Scrive la FK Macchina.asset (default: solo simulazione).")
        parser.add_argument("--ricollega", action="store_true",
                            help="Considera anche le macchine gia' collegate (default: solo quelle senza asset).")

    def handle(self, *args, **opts):
        from assets.models import Asset  # import lazy: app dell'HUB

        apply = opts["apply"]
        qs = Macchina.objects.all()
        if not opts["ricollega"]:
            qs = qs.filter(asset__isnull=True)

        collegate = ambigue = non_trovate = 0
        for m in qs:
            match, motivo = None, ""
            mat = (m.matricola or "").strip()
            if mat:
                cand = list(Asset.objects.filter(serial_number__iexact=mat))
                if len(cand) == 1:
                    match, motivo = cand[0], "matricola↔serial"
                elif len(cand) > 1:
                    ambigue += 1
                    self.stdout.write(self.style.WARNING(
                        f"AMBIGUO serial per «{m}»: {len(cand)} asset con serial={mat}"))
                    continue
            if match is None and m.host:
                cand = list(Asset.objects.filter(endpoints__ip=str(m.host)).distinct())
                if len(cand) == 1:
                    match, motivo = cand[0], "host↔ip"
                elif len(cand) > 1:
                    ambigue += 1
                    self.stdout.write(self.style.WARNING(
                        f"AMBIGUO ip per «{m}»: {len(cand)} asset con ip={m.host}"))
                    continue
            if match is None:
                non_trovate += 1
                continue
            collegate += 1
            self.stdout.write(
                f"{'COLLEGO' if apply else 'MATCH  '} «{m}» -> Asset «{match.name}» "
                f"[{match.asset_tag}] ({motivo})")
            if apply:
                m.asset = match
                m.save(update_fields=["asset"])

        verbo = "collegate" if apply else "match trovati"
        suffix = "" if apply else "  [DRY-RUN: usa --apply per scrivere]"
        self.stdout.write(self.style.SUCCESS(
            f"\n{collegate} {verbo}, {ambigue} ambigui (saltati), "
            f"{non_trovate} senza corrispondenza.{suffix}"))
