"""Crea impianti e tipi di verifica periodica dal catalogo iniziale.

Catalogo in ``assets/services/periodic_checks_catalog.py`` (registro Bruschi +
cartelle di ``\\\\novisrv\\privman``). Idempotente: impianti e tipi si riconoscono
dal nome e non vengono modificati se esistono gia' (le modifiche fatte dal portale
restano). Il fornitore si aggancia all'anagrafica solo se la ragione sociale
contiene l'indizio del catalogo ed e' univoca. Di default e' una prova a vuoto;
scrive solo con ``--apply``.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from anagrafica.models import Fornitore
from assets.models import PeriodicCheckItem, PeriodicCheckSystem, PeriodicCheckType
from assets.services.periodic_checks_catalog import CATALOG, SYSTEMS


def _supplier_for(hint: str):
    if not hint:
        return None
    matches = list(Fornitore.objects.filter(ragione_sociale__icontains=hint, is_active=True)[:2])
    return matches[0] if len(matches) == 1 else None


class Command(BaseCommand):
    help = "Crea impianti e tipi di verifica periodica dal catalogo (default: prova a vuoto)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Scrive davvero (senza: solo elenco).")

    def handle(self, *args, **options):
        apply = bool(options.get("apply"))
        with transaction.atomic():
            systems = {}
            for name, description, order in SYSTEMS:
                system = PeriodicCheckSystem.objects.filter(name=name).first()
                if system is None:
                    self.stdout.write(f"+ impianto  {name}")
                    system = PeriodicCheckSystem.objects.create(name=name, description=description, sort_order=order)
                systems[name] = system
            for entry in CATALOG:
                system = systems[entry.system]
                if PeriodicCheckType.objects.filter(system=system, name=entry.name).exists():
                    self.stdout.write(f"= tipo      {entry.system} / {entry.name} (gia' presente)")
                    continue
                supplier = _supplier_for(entry.supplier_hint)
                check_type = PeriodicCheckType.objects.create(
                    system=system,
                    name=entry.name,
                    reference_code=entry.reference_code,
                    method=entry.method,
                    frequency_months=entry.frequency_months,
                    supplier=supplier,
                    executor_label="" if supplier else entry.executor,
                    legal_reference=entry.legal_reference,
                    archive_folder="; ".join(s.folder for s in entry.sources),
                    sort_order=entry.sort_order,
                )
                for index, label in enumerate(entry.items):
                    PeriodicCheckItem.objects.create(check_type=check_type, label=label, sort_order=(index + 1) * 10)
                who = f"fornitore {supplier}" if supplier else (entry.executor or "esecutore da indicare")
                self.stdout.write(
                    f"+ tipo      {entry.system} / {entry.name} · ogni {entry.frequency_months} mesi · {who}"
                    + (f" · {len(entry.items)} voci" if entry.items else "")
                )
            if not apply:
                transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS("Fatto." if apply else "Prova a vuoto: nulla e' stato scritto (usa --apply)."))
