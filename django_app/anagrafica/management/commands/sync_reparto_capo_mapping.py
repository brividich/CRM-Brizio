"""
Sincronizza RepartoCapoMapping (usata da assenze e automazioni) dai dati
dei Reparto in Anagrafica HR (Reparto.caporeparto_legacy_id).

Eseguire una volta dopo la migrazione dalla gestione in admin_portale/anagrafica-config:

    python manage.py sync_reparto_capo_mapping
    python manage.py sync_reparto_capo_mapping --dry-run
"""

from django.core.management.base import BaseCommand

from anagrafica.models import Reparto
from core.caporeparto_utils import canonical_caporeparto_value
from core.models import RepartoCapoMapping


class Command(BaseCommand):
    help = "Allinea RepartoCapoMapping ai caporeparto definiti in Anagrafica HR (Reparto.caporeparto_legacy_id)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra le operazioni senza applicarle.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        reparti = Reparto.objects.all().order_by("nome")
        created = updated = deleted = skipped = 0

        for rep in reparti:
            nome = (rep.nome or "").strip()
            if not nome:
                continue

            existing = list(RepartoCapoMapping.objects.filter(reparto__iexact=nome))

            if not rep.caporeparto_legacy_id:
                if existing:
                    self.stdout.write(f"  DEL  {nome!r} → nessun caporeparto (rimuovo {len(existing)} mapping)")
                    if not dry_run:
                        RepartoCapoMapping.objects.filter(reparto__iexact=nome).delete()
                    deleted += len(existing)
                else:
                    skipped += 1
                continue

            capo_str = canonical_caporeparto_value(legacy_user_id=rep.caporeparto_legacy_id)
            if not capo_str:
                self.stdout.write(self.style.WARNING(
                    f"  SKIP {nome!r}: legacy_id={rep.caporeparto_legacy_id} non risolto"
                ))
                skipped += 1
                continue

            if len(existing) == 1 and existing[0].caporeparto == capo_str and existing[0].is_active:
                skipped += 1
                continue

            if not dry_run:
                RepartoCapoMapping.objects.filter(reparto__iexact=nome).delete()
                RepartoCapoMapping.objects.create(reparto=nome, caporeparto=capo_str, is_active=True)

            if existing:
                self.stdout.write(f"  UPD  {nome!r} → {capo_str!r}")
                updated += 1
            else:
                self.stdout.write(f"  ADD  {nome!r} → {capo_str!r}")
                created += 1

        suffix = " [DRY-RUN]" if dry_run else ""
        self.stdout.write(self.style.SUCCESS(
            f"\nDone{suffix}: {created} creati, {updated} aggiornati, {deleted} eliminati, {skipped} invariati."
        ))
