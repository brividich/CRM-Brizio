"""Solleciti/escalation Suggestion Corner (§3).

Per le segnalazioni in DO_IN_CORSO/CHECK_IN_CORSO con scadenza valorizzata,
invia UN sollecito per la banda di scadenza più stretta in cui cade la data
(30/15/5 giorni), una sola volta per banda (flag sul modello), più
un'escalation al responsabile oltre la soglia. Da agganciare a django-q.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from suggestion_corner import notifications as N
from suggestion_corner.models import SuggestionCorner, SuggestionCornerConfig


class Command(BaseCommand):
    help = "Invia solleciti ed escalation per le segnalazioni Suggestion Corner."

    def handle(self, *args, **options):
        cfg = SuggestionCornerConfig.load()
        today = timezone.localdate()
        sent = 0
        for seg in SuggestionCorner.objects.filter(
            stato="DO_IN_CORSO", data_limite_esecuzione__isnull=False,
        ):
            sent += self._process(
                seg, "DO", (seg.data_limite_esecuzione - today).days, cfg,
                email=seg.incaricato.email if seg.incaricato_id else "",
                flags=("sollecito_do_30", "sollecito_do_15", "sollecito_do_5", "escalation_do_inviata"),
            )
        for seg in SuggestionCorner.objects.filter(
            stato="CHECK_IN_CORSO", data_limite_controllo__isnull=False,
        ):
            sent += self._process(
                seg, "CHECK", (seg.data_limite_controllo - today).days, cfg,
                email=seg.controllore.email if seg.controllore_id else "",
                flags=("sollecito_check_30", "sollecito_check_15", "sollecito_check_5", "escalation_check_inviata"),
            )
        self.stdout.write(self.style.SUCCESS(f"Suggestion Corner: {sent} email inviate."))
        return None

    def _process(self, seg, fase, days, cfg, *, email, flags):
        f30, f15, f5, fesc = flags

        # Escalation: scaduta oltre la soglia → responsabile, una volta sola.
        if days < -cfg.giorni_escalation_oltre_scadenza:
            if not getattr(seg, fesc):
                n = N._escalation(seg, fase)
                setattr(seg, fesc, True)
                seg.save(update_fields=[fesc])
                return n
            return 0

        # Banda di scadenza: solo la PIÙ STRETTA in cui cade `days` (no fallthrough).
        if days <= cfg.giorni_sollecito_3:
            target = f5
        elif days <= cfg.giorni_sollecito_2:
            target = f15
        elif days <= cfg.giorni_sollecito_1:
            target = f30
        else:
            return 0

        if getattr(seg, target):
            return 0
        n = N._sollecito(email, seg, fase, days)
        setattr(seg, target, True)
        seg.save(update_fields=[target])
        return n
