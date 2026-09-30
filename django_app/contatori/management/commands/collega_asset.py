"""Riconcilia MFC e dispositivi SNMP con il registro Asset HUB.

Match univoco per seriale, poi per IP di AssetEndpoint. Dry-run di default;
scrive soltanto le FK nel modulo contatori e non modifica mai gli Asset.
"""
from django.core.management.base import BaseCommand

from contatori import services
from contatori.models import DispositivoSNMP, Macchina


class Command(BaseCommand):
    help = (
        "Collega MFC/dispositivi SNMP agli Asset (seriale, poi endpoint IP). "
        "Dry-run salvo --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Scrive le FK asset (default: solo simulazione).",
        )
        parser.add_argument(
            "--ricollega", action="store_true",
            help="Considera anche gli endpoint già collegati.",
        )

    def handle(self, *args, **opts):
        elementi = []
        mfc = Macchina.objects.all()
        dispositivi = DispositivoSNMP.objects.all()
        if not opts["ricollega"]:
            mfc = mfc.filter(asset__isnull=True)
            dispositivi = dispositivi.filter(asset__isnull=True)
        elementi.extend(("MFC", obj, obj.matricola, obj.host) for obj in mfc)
        elementi.extend(
            ("SNMP", obj, obj.matricola, obj.host) for obj in dispositivi
        )

        collegate = ambigue = non_trovate = 0
        for tipo, obj, seriale, host in elementi:
            asset, motivo = services.trova_asset_snmp(
                seriale=seriale, host=host,
            )
            if asset is None:
                if "ambiguo" in motivo:
                    ambigue += 1
                    self.stdout.write(self.style.WARNING(
                        f"AMBIGUO {tipo} «{obj}»: {motivo}",
                    ))
                else:
                    non_trovate += 1
                continue
            collegate += 1
            self.stdout.write(
                f"{'COLLEGO' if opts['apply'] else 'MATCH  '} {tipo} «{obj}» -> "
                f"Asset «{asset.name}» [{asset.asset_tag}] ({motivo})"
            )
            if opts["apply"]:
                obj.asset = asset
                fields = ["asset"]
                if isinstance(obj, DispositivoSNMP):
                    fields.append("aggiornato_il")
                obj.save(update_fields=fields)

        verbo = "collegati" if opts["apply"] else "match trovati"
        suffix = "" if opts["apply"] else " [DRY-RUN: usa --apply per scrivere]"
        self.stdout.write(self.style.SUCCESS(
            f"{collegate} {verbo}, {ambigue} ambigui, "
            f"{non_trovate} senza corrispondenza.{suffix}"
        ))
