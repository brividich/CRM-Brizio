"""Rimette lo stato giusto alle richieste decise via mail e tornate «In attesa».

Prima della correzione, l'approvazione via mail (azione ``update_trigger_record``)
cambiava solo ``moderation_status``: SharePoint restava «In attesa» e la lettura
successiva riportava indietro la richiesta (#9656, #9727). Questo comando trova le
richieste con una decisione registrata (``AutomationApproval`` approvata o
rifiutata) che oggi risultano ancora in attesa, e le riallinea: stato, consenso,
data di approvazione e invio a SharePoint. Le mail non ripartono (sono già state
mandate al momento della decisione).

Senza ``--applica`` mostra soltanto cosa farebbe.
"""
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Riallinea le richieste di assenza decise via mail ma tornate «In attesa» (anteprima senza --applica)."

    def add_arguments(self, parser):
        parser.add_argument("--applica", action="store_true", help="Scrive davvero le correzioni.")

    def handle(self, *args, **opts):
        from automazioni.models import AutomationApproval

        from assenze.views import _helpers

        decisioni: dict[int, AutomationApproval] = {}
        qs = (AutomationApproval.objects
              .filter(status__in=[AutomationApproval.Status.APPROVED, AutomationApproval.Status.REJECTED],
                      run_log__source_code="assenze")
              .order_by("decided_at", "id"))
        for a in qs:
            payload = a.resume_payload if isinstance(a.resume_payload, dict) else {}
            pk = _helpers._as_int(payload.get("id"))
            if pk is not None:
                decisioni[pk] = a  # l'ultima decisione vince

        da_fare = []
        for pk, a in sorted(decisioni.items()):
            riga = _helpers._get_assenza(pk)
            if not riga:
                continue
            mod = _helpers._as_int(riga.get("moderation_status"))
            if (mod if mod is not None else 2) != 2:
                continue
            nuovo = 0 if a.status == AutomationApproval.Status.APPROVED else 1
            da_fare.append((pk, nuovo, a))

        if not da_fare:
            self.stdout.write("Nessuna richiesta da riallineare.")
            return
        for pk, nuovo, a in da_fare:
            esito = "Approvato" if nuovo == 0 else "Rifiutato"
            quando = a.decided_at.strftime("%d/%m/%Y %H:%M") if a.decided_at else "?"
            self.stdout.write(f"#{pk}: In attesa -> {esito} (decisa il {quando} da {a.decided_by_email or '?'})")
        if not opts["applica"]:
            self.stdout.write(f"Anteprima: {len(da_fare)} richieste. Rilancia con --applica per correggerle.")
            return

        for pk, nuovo, _a in da_fare:
            with transaction.atomic():
                _helpers._set_automation_queue_skip(True)
                try:
                    _helpers._update_assenza(pk, {"moderation_status": nuovo})
                finally:
                    _helpers._set_automation_queue_skip(False)
                _helpers.allinea_dopo_automazione(pk, ["moderation_status"])
            _helpers.log_action(None, "assenza_riallineata_dopo_mail", "assenze", {"item_id": pk, "moderation_status": nuovo})
        self.stdout.write(f"Riallineate {len(da_fare)} richieste; l'invio a SharePoint parte col prossimo giro.")
