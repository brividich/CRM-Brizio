"""Audit della classificazione dei permessi in livelli d'accesso.

Di sola lettura: nessuna scrittura, nessuna migrazione, si puo' lanciare in
produzione per vedere cosa i livelli della pagina Accessi accenderebbero
davvero su quel catalogo.

    python django_app/manage.py acl_capability_report
    python django_app/manage.py acl_capability_report --only-unclassified
    python django_app/manage.py acl_capability_report --format json

Tre cose che vale la pena guardare:

* **Non classificati**: permessi il cui nome non dice cosa facciano. Nessun
  livello li accende tranne "Amministratore del modulo". Se sono tanti in un
  modulo, quel modulo non e' governabile dai livelli e va guardato a mano.
* **Alzati dal sottoalbero**: permessi legati a un prefisso di URL che governano
  anche rotte di scrittura. Il nome diceva "lettura", cio' che coprono dice di
  piu'. Sono il motivo per cui questo comando esiste.
* **Per livello**: quanti permessi accenderebbe ciascun livello.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from core.acl_capability import capability_index
from core.permission_taxonomy import (
    ACCESS_LEVELS,
    CAPABILITY_ORDER,
    capability_label,
)


class Command(BaseCommand):
    help = "Mostra come i permessi canonici si classificano nei livelli d'accesso (sola lettura)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--format",
            choices=["text", "json"],
            default="text",
            help="Formato di uscita (default: text).",
        )
        parser.add_argument(
            "--only-unclassified",
            action="store_true",
            help="Stampa solo i permessi che nessun livello sotto l'ultimo accende.",
        )
        parser.add_argument(
            "--module",
            default="",
            help="Limita il report a un modulo (prefisso del code o campo module).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Numero massimo di righe per elenco (0 = tutte).",
        )

    def handle(self, *args, **options):
        index = capability_index(use_cache=False)
        module = str(options.get("module") or "").strip().lower()
        limit = int(options.get("limit") or 0)

        capabilities = index.capabilities
        if module:
            capabilities = {
                code: capability
                for code, capability in capabilities.items()
                if code.startswith(f"{module}.") or f".{module}." in code
            }

        per_capability = {name: 0 for name in CAPABILITY_ORDER}
        for capability in capabilities.values():
            per_capability[capability] = per_capability.get(capability, 0) + 1

        unclassified = [code for code in index.unclassified() if code in capabilities]
        promoted = {
            code: pair for code, pair in index.promoted().items() if code in capabilities
        }

        per_level = {}
        for level in ACCESS_LEVELS:
            per_level[level["key"]] = sum(
                1 for capability in capabilities.values() if capability in level["capabilities"]
            )

        if options["format"] == "json":
            payload = {
                "totale": len(capabilities),
                "per_capacita": per_capability,
                "per_livello": per_level,
                "non_classificati": unclassified,
                "alzati_dal_sottoalbero": {
                    code: {
                        "dal_nome": pair[0],
                        "effettiva": pair[1],
                        "rotte": index.subtree_routes.get(code, []),
                    }
                    for code, pair in promoted.items()
                },
            }
            self.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False))
            return

        self.stdout.write(self.style.MIGRATE_HEADING(f"Permessi attivi: {len(capabilities)}"))
        if options["only_unclassified"]:
            self._write_unclassified(unclassified, limit)
            return

        self.stdout.write("\nPer capacita':")
        for name in CAPABILITY_ORDER:
            self.stdout.write(f"  {per_capability.get(name, 0):5}  {capability_label(name)}")

        self.stdout.write("\nQuanti permessi accende ciascun livello:")
        for level in ACCESS_LEVELS:
            self.stdout.write(f"  {per_level[level['key']]:5}  {level['label']}")

        self.stdout.write(
            f"\nAlzati da cio' che governano (binding di prefisso): {len(promoted)}"
        )
        rows = sorted(promoted.items())
        for code, (from_name, effective) in rows[: limit or len(rows)]:
            causes = [
                route
                for route, capability in index.subtree_routes.get(code, [])
                if capability == effective
            ]
            sample = ", ".join(sorted(causes)[:3])
            self.stdout.write(
                f"  {code}\n      {capability_label(from_name)} -> {capability_label(effective)}"
                + (f"  ({sample})" if sample else "")
            )

        self._write_unclassified(unclassified, limit)

    def _write_unclassified(self, unclassified: list[str], limit: int) -> None:
        self.stdout.write(
            f"\nNon classificati (li accende solo 'Amministratore del modulo'): {len(unclassified)}"
        )
        for code in unclassified[: limit or len(unclassified)]:
            self.stdout.write(f"  {code}")
