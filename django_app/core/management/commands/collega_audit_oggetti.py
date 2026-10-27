"""Aggancia al record le voci di audit automatiche scritte prima che i segnali lo facessero.

Fino al 27/10/2026 le righe ``auto_insert``/``auto_update``/``auto_delete`` non
valorizzavano ``oggetto_tipo``/``oggetto_id``: restavano fuori dagli storici per
scheda (``core.audit.storico_oggetto``). Il modello e la chiave però sono nel
``dettaglio`` (``model``, ``pk``) e il ``modulo`` è l'app: da lì si ricavano.

Tocca **solo** le righe ``auto_*`` ancora senza aggancio, che il sigillo mensile
dell'audit non copre (``core.audit_sigilli.AUTO_AZIONI``): i sigilli restano validi.

    python manage.py collega_audit_oggetti --dry-run
    python manage.py collega_audit_oggetti --app anagrafica
"""
from __future__ import annotations

from django.apps import apps
from django.core.management.base import BaseCommand

from core.audit_sigilli import AUTO_AZIONI


class Command(BaseCommand):
    help = "Aggancia al record (oggetto_tipo/oggetto_id) le voci di audit automatiche che ne sono prive."

    def add_arguments(self, parser):
        parser.add_argument("--app", action="append", default=[],
                            help="Solo le voci di queste app (ripetibile). Default: tutte.")
        parser.add_argument("--batch", type=int, default=1000, help="Righe per blocco (default 1000).")
        parser.add_argument("--dry-run", action="store_true", help="Conta senza scrivere.")

    def handle(self, *args, **opts):
        from core.models import AuditLog

        batch = max(100, int(opts["batch"]))
        dry = bool(opts["dry_run"])
        qs = AuditLog.objects.filter(azione__in=AUTO_AZIONI, oggetto_tipo="")
        if opts["app"]:
            qs = qs.filter(modulo__in=opts["app"])

        etichette: dict[tuple[str, str], str] = {}

        def _etichetta(modulo: str, nome: str) -> str:
            chiave = (modulo, nome)
            if chiave not in etichette:
                try:
                    etichette[chiave] = apps.get_model(modulo, nome)._meta.label_lower
                except (LookupError, ValueError):
                    etichette[chiave] = ""
            return etichette[chiave]

        ultimo = 0
        collegate = saltate = 0
        while True:
            blocco = list(qs.filter(pk__gt=ultimo).order_by("pk").only("pk", "modulo", "dettaglio")[:batch])
            if not blocco:
                break
            ultimo = blocco[-1].pk
            da_scrivere = []
            for voce in blocco:
                dettaglio = voce.dettaglio if isinstance(voce.dettaglio, dict) else {}
                tipo = _etichetta(voce.modulo or "", str(dettaglio.get("model") or ""))
                pk = str(dettaglio.get("pk") or "")
                if not tipo or not pk:
                    saltate += 1
                    continue
                voce.oggetto_tipo = tipo[:100]
                voce.oggetto_id = pk[:64]
                da_scrivere.append(voce)
            collegate += len(da_scrivere)
            if da_scrivere and not dry:
                # 200 righe: CASE per due campi resta sotto i 2100 parametri di SQL Server.
                AuditLog.objects.bulk_update(da_scrivere, ["oggetto_tipo", "oggetto_id"], batch_size=200)

        verbo = "da collegare" if dry else "collegate"
        self.stdout.write(self.style.SUCCESS(
            f"Voci automatiche {verbo}: {collegate}; senza modello o chiave riconoscibili: {saltate}."
        ))
