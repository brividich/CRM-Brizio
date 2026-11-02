"""Ricostruisce le date dei tempi (prima decisione, chiusura) per le anomalie gia' esistenti.

Da qui in avanti le date le scrive il salvataggio dell'anomalia
(``tempi_service.aggiorna_tempi``). Per lo storico si leggono dalla cronologia azioni
(``AnomaliaActionLog``): prima decisione = primo aggiornamento o chiusura, chiusura =
ultima chiusura se l'anomalia e' ancora chiusa. Una data gia' scritta non si tocca.
E' un'approssimazione: nella cronologia «aggiornata» puo' essere anche una correzione
del testo. L'attesa del cliente non si ricostruisce (lo stato non esisteva).

    manage.py anomalie_tempi_ricostruisci            # dry-run
    manage.py anomalie_tempi_ricostruisci --apply
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from anomalie import qualita_service as qs
from anomalie.automazioni_service import _anomalie_cols, _fetch
from anomalie.mail_action_models import AnomaliaActionLog
from anomalie.quality_models import AnomaliaSchedaQualita

_DECISIONI = ("aggiorna", "aggiorna_avanzamento", "chiudi", "approva", "respingi", "richiedi_modifica")


class Command(BaseCommand):
    help = "Ricostruisce dalla cronologia le date dei tempi delle anomalie (dry-run di default)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Scrive davvero (default: dry-run).")

    def handle(self, *args, **opts):
        if "id" not in _anomalie_cols():
            self.stderr.write("Tabella anomalie non disponibile.")
            return
        ids = [int(r["id"]) for r in _fetch("SELECT id FROM anomalie ORDER BY id", [])]
        righe = qs.legacy_rows(ids)
        prima: dict[int, object] = {}
        chiusura: dict[int, object] = {}
        for aid, azione, quando in AnomaliaActionLog.objects.filter(
            anomalia_id__in=ids, action__in=_DECISIONI,
        ).order_by("created_at").values_list("anomalia_id", "action", "created_at"):
            prima.setdefault(aid, quando)
            if azione == "chiudi":
                chiusura[aid] = quando

        da_scrivere = []
        for aid in ids:
            row = righe.get(aid)
            if row is None:
                continue
            campi = {}
            scheda = AnomaliaSchedaQualita.objects.filter(anomalia_id=aid).first()
            if aid in prima and (scheda is None or scheda.prima_decisione_il is None):
                campi["prima_decisione_il"] = prima[aid]
                campi["primo_avanzamento"] = str(row.get("avanzamento") or "").strip()[:100]
            if row.get("chiudere") and (scheda is None or scheda.chiusa_il is None):
                campi["chiusa_il"] = chiusura.get(aid) or prima.get(aid)
                if campi["chiusa_il"] is None:
                    campi.pop("chiusa_il")
            if campi:
                da_scrivere.append((aid, row, campi))
        self.stdout.write(f"Anomalie: {len(ids)} · da completare: {len(da_scrivere)}")
        if not opts["apply"]:
            self.stdout.write("Dry-run: nessuna modifica. Rilancia con --apply.")
            return
        for aid, row, campi in da_scrivere:
            scheda, _ = qs.get_or_create_scheda(aid, row=row)
            if scheda is not None:
                AnomaliaSchedaQualita.objects.filter(pk=scheda.pk).update(**campi)
        self.stdout.write(self.style.SUCCESS(f"Schede completate: {len(da_scrivere)}"))
