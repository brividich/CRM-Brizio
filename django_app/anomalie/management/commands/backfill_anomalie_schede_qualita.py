"""Crea le schede qualita' mancanti per le anomalie gia' esistenti.

Le schede (e la NC dell'OP) nascono da sole al salvataggio dell'anomalia o alla sua
prima apertura nel dettaglio. Questo comando le crea in blocco, in ordine di id.
Di default NON crea le NC per lo storico: ogni OP storico diventerebbe una NC
aperta da gestire. Con ``--nc`` raggruppa anche lo storico in NC per OP.

    manage.py backfill_anomalie_schede_qualita            # dry-run
    manage.py backfill_anomalie_schede_qualita --apply
    manage.py backfill_anomalie_schede_qualita --apply --nc
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from anomalie import nc_service
from anomalie import qualita_service as qs
from anomalie.automazioni_service import _anomalie_cols, _fetch
from anomalie.quality_models import AnomaliaSchedaQualita


class Command(BaseCommand):
    help = "Crea le schede qualita' mancanti per le anomalie esistenti (dry-run di default)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Scrive davvero (default: dry-run).")
        parser.add_argument("--nc", action="store_true",
                            help="Aggancia lo storico anche a una NC per OP (default: no).")

    def handle(self, *args, **opts):
        if "id" not in _anomalie_cols():
            self.stderr.write("Tabella anomalie non disponibile.")
            return
        esistenti = set(AnomaliaSchedaQualita.objects.values_list("anomalia_id", flat=True))
        ids = [int(r["id"]) for r in _fetch("SELECT id FROM anomalie ORDER BY id", [])]
        mancanti = [i for i in ids if i not in esistenti]
        self.stdout.write(f"Anomalie: {len(ids)} · con scheda: {len(esistenti)} · da creare: {len(mancanti)}")
        if not opts["apply"]:
            self.stdout.write("Dry-run: nessuna modifica. Rilancia con --apply.")
            return
        righe = qs.legacy_rows(mancanti)
        create, nc = 0, set()
        for anomalia_id in mancanti:
            row = righe.get(anomalia_id)
            if row is None:
                continue
            scheda, creata = qs.get_or_create_scheda(anomalia_id, row=row)
            create += int(bool(creata))
            if scheda is not None and opts["nc"]:
                n = nc_service.aggancia_a_nc(scheda, row)
                if n is not None:
                    nc.add(n.pk)
        msg = f"Schede create: {create}" + (f" · NC coinvolte: {len(nc)}" if opts["nc"] else "")
        self.stdout.write(self.style.SUCCESS(msg))
