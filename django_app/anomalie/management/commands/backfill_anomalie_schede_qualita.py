"""Crea le schede qualita' mancanti per le anomalie gia' esistenti.

Le schede nascono da sole al salvataggio (o all'apertura nel dettaglio); questo
comando le crea in blocco in ordine di id, cosi' i protocolli ``NC-<anno>-<nnnn>``
seguono l'ordine cronologico di creazione. Di default NON registra nulla nel
registro NC: lo storico resterebbe altrimenti una valanga di voci da gestire.

    manage.py backfill_anomalie_schede_qualita            # dry-run
    manage.py backfill_anomalie_schede_qualita --apply
    manage.py backfill_anomalie_schede_qualita --apply --registro-nc   # anche NC
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from anomalie import qualita_service as qs
from anomalie.automazioni_service import _anomalie_cols, _fetch
from anomalie.quality_models import AnomaliaSchedaQualita


class Command(BaseCommand):
    help = "Crea le schede qualita' mancanti per le anomalie esistenti (dry-run di default)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Scrive davvero (default: dry-run).")
        parser.add_argument("--registro-nc", action="store_true",
                            help="Valuta anche la registrazione nel registro NC (default: no).")

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
        create, nc = 0, 0
        for anomalia_id in mancanti:
            row = qs.legacy_row(anomalia_id)
            if row is None:
                continue
            scheda, creata = qs.get_or_create_scheda(anomalia_id, row=row)
            create += int(bool(creata))
            if scheda is not None and opts["registro_nc"]:
                nc += int(qs.valuta_registro_nc(scheda, row) is not None)
        self.stdout.write(self.style.SUCCESS(f"Schede create: {create}" + (f" · collegate a NC: {nc}" if opts["registro_nc"] else "")))
