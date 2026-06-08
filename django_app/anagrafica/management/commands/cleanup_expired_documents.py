"""Cancella i DocumentoDipendente scaduti secondo la retention policy GDPR.

Criteri di eliminazione (tutti e tre devono essere veri):
  1. ``retention_until`` è impostato ed è passato (< oggi).
  2. Il dipendente ha una data di cessazione valorizzata (non è attivo).
  3. ``data_cessazione + anni_retention`` è anch'essa passata.

Il punto 3 garantisce che il documento non venga eliminato prima che siano
trascorsi gli anni di legge dalla fine del rapporto, indipendentemente da
quando il documento è stato caricato.

Opzioni:
  (default)   Dry-run: mostra cosa verrebbe eliminato senza toccare nulla.
  --apply     Esegue la cancellazione effettiva.
  --backfill  Popola retention_until=null sui documenti pre-migrazione
              usando created_at + anni_retention. Non elimina nulla.
  --tipo      Limita a un tipo documento (es. VISITA_MEDICA_REFERTO).
  --limit     Numero massimo di documenti da elaborare per run (default 500).
"""
from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from anagrafica.models import DipendenteAnagraficaAziendale, DocumentoDipendente, _add_months

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Gestisce la retention GDPR dei DocumentoDipendente (cleanup + backfill)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Esegue la cancellazione effettiva. Senza questo flag è dry-run.",
        )
        parser.add_argument(
            "--backfill",
            action="store_true",
            default=False,
            help="Popola retention_until sui documenti che ce l'hanno null (pre-migrazione).",
        )
        parser.add_argument(
            "--tipo",
            type=str,
            default="",
            help="Limita a un tipo documento (es. VISITA_MEDICA_REFERTO).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=500,
            help="Numero massimo di documenti da elaborare per run (default 500).",
        )

    def handle(self, *args, **options):
        if options["backfill"]:
            self._handle_backfill(options)
        else:
            self._handle_cleanup(options)

    def _handle_backfill(self, options):
        tipo_filter = (options.get("tipo") or "").strip().upper()
        limit = max(1, options["limit"])
        oggi = timezone.localdate()

        self.stdout.write(f"cleanup_expired_documents --backfill | data: {oggi}")

        qs = DocumentoDipendente.objects.filter(retention_until__isnull=True).order_by("id")
        if tipo_filter:
            qs = qs.filter(tipo=tipo_filter)

        da_aggiornare = []
        for doc in qs[:limit]:
            anni = DocumentoDipendente._RETENTION_ANNI.get(doc.tipo, 10)
            base = doc.created_at.date() if doc.created_at else oggi
            doc.retention_until = _add_months(base, anni * 12)
            da_aggiornare.append(doc)

        if da_aggiornare:
            DocumentoDipendente.objects.bulk_update(da_aggiornare, ["retention_until"])

        self.stdout.write(self.style.SUCCESS(
            f"Backfill completato | aggiornati={len(da_aggiornare)}"
        ))

    def _handle_cleanup(self, options):
        apply = options["apply"]
        tipo_filter = (options.get("tipo") or "").strip().upper()
        limit = max(1, options["limit"])
        oggi = timezone.localdate()

        mode = "APPLY" if apply else "DRY-RUN"
        self.stdout.write(f"cleanup_expired_documents | modalità: {mode} | data: {oggi}")

        qs = DocumentoDipendente.objects.filter(
            retention_until__isnull=False,
            retention_until__lt=oggi,
        ).order_by("retention_until", "id")

        if tipo_filter:
            qs = qs.filter(tipo=tipo_filter)

        # Carica cessazioni in blocco per evitare N+1.
        legacy_ids = list(qs.values_list("legacy_anagrafica_id", flat=True).distinct())
        cessazioni = {
            row["legacy_anagrafica_id"]: row["data_cessazione"]
            for row in DipendenteAnagraficaAziendale.objects.filter(
                legacy_anagrafica_id__in=legacy_ids
            ).values("legacy_anagrafica_id", "data_cessazione")
        }

        totali = {"esaminati": 0, "saltati_attivi": 0, "saltati_retention": 0, "eliminati": 0, "errori": 0}
        for doc in qs[:limit]:
            totali["esaminati"] += 1
            cessazione = cessazioni.get(doc.legacy_anagrafica_id)

            # Dipendente ancora attivo → non eliminare mai.
            if cessazione is None:
                totali["saltati_attivi"] += 1
                continue

            # Verifica che siano trascorsi gli anni di retention anche dalla cessazione.
            anni = DocumentoDipendente._RETENTION_ANNI.get(doc.tipo, 10)
            if _add_months(cessazione, anni * 12) >= oggi:
                totali["saltati_retention"] += 1
                continue

            label = (
                f"doc#{doc.pk} [{doc.legacy_anagrafica_id}] {doc.tipo} "
                f"cessato={cessazione} retention_until={doc.retention_until}"
            )
            if apply:
                try:
                    doc.delete()
                    totali["eliminati"] += 1
                    logger.info("GDPR cleanup: eliminato %s", label)
                    self.stdout.write(f"  ELIMINATO {label}")
                except Exception:
                    totali["errori"] += 1
                    logger.exception("GDPR cleanup: errore eliminazione %s", label)
                    self.stdout.write(self.style.ERROR(f"  ERRORE {label}"))
            else:
                totali["eliminati"] += 1
                self.stdout.write(f"  [DRY-RUN] da eliminare: {label}")

        summary = (
            f"Completato | esaminati={totali['esaminati']} "
            f"saltati_attivi={totali['saltati_attivi']} "
            f"saltati_retention={totali['saltati_retention']} "
            f"{'eliminati' if apply else 'da_eliminare'}={totali['eliminati']} "
            f"errori={totali['errori']}"
        )
        style = self.style.SUCCESS if not totali["errori"] else self.style.WARNING
        self.stdout.write(style(summary))
