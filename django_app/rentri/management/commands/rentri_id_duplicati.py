"""Audit di sola lettura sui numeri di registrazione duplicati del registro RENTRI.

Eseguibile in produzione: non scrive nulla, serve a portare al responsabile
l'elenco dei casi da decidere prima di poter imporre l'unicità a database.
"""
from __future__ import annotations

import csv
import json
import sys

from django.core.management.base import BaseCommand

from ...numerazione import id_duplicati


class Command(BaseCommand):
    help = "Elenca i numeri di registrazione usati da più di un movimento (sola lettura)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--format", choices=["table", "csv", "json"], default="table",
            help="Formato di output (default: table).",
        )
        parser.add_argument(
            "--solo-anomalie", action="store_true",
            help="Esclude le coppie R+M dello stesso giorno (registrazione congiunta).",
        )

    def handle(self, *args, **options):
        gruppi = id_duplicati()
        if options["solo_anomalie"]:
            gruppi = [g for g in gruppi if not g["coppia_rm"]]

        if options["format"] == "json":
            self.stdout.write(json.dumps(self._as_rows(gruppi), ensure_ascii=False, indent=2, default=str))
            return
        if options["format"] == "csv":
            writer = csv.DictWriter(
                sys.stdout,
                fieldnames=["id_registrazione", "coppia_rm", "tipo", "data", "codice", "quantita", "rif_op", "pk"],
                delimiter=";", lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(self._as_rows(gruppi))
            return

        anomalie = [g for g in gruppi if not g["coppia_rm"]]
        coppie = len(gruppi) - len(anomalie)
        self.stdout.write(self.style.MIGRATE_HEADING(
            f"{len(gruppi)} numeri duplicati — {len(anomalie)} anomalie, {coppie} coppie R+M dello stesso giorno"
        ))
        for gruppo in gruppi:
            etichetta = "coppia R+M" if gruppo["coppia_rm"] else "ANOMALIA"
            stile = self.style.SUCCESS if gruppo["coppia_rm"] else self.style.ERROR
            cer = " / ".join(gruppo["codici"]) or "—"
            self.stdout.write("")
            self.stdout.write(stile(f"{gruppo['id_registrazione']}  [{etichetta}]  {cer}"))
            for r in gruppo["righe"]:
                self.stdout.write(
                    f"    {r.tipo}  {r.data}  {(r.codice or '—')[:44]:<44}"
                    f"  q={r.quantita if r.quantita is not None else '—'}"
                    f"  rif_op={r.rif_op or '—'}  pk={r.pk}"
                )

    @staticmethod
    def _as_rows(gruppi) -> list[dict]:
        return [
            {
                "id_registrazione": gruppo["id_registrazione"],
                "coppia_rm": gruppo["coppia_rm"],
                "tipo": r.tipo,
                "data": r.data,
                "codice": r.codice,
                "quantita": r.quantita,
                "rif_op": r.rif_op,
                "pk": r.pk,
            }
            for gruppo in gruppi
            for r in gruppo["righe"]
        ]
