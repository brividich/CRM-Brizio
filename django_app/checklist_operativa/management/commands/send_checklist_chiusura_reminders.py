"""Promemoria ai responsabili con task non confermati prima di una chiusura.

Due canali, con due granularità diverse **di proposito**:

* **in-app**: una notifica per voce, com'è sempre stato — nel campanello del
  portale ogni riga è un'azione da spuntare;
* **email**: **una sola** email per responsabile e per evento, con l'elenco
  delle sue voci mancanti. Il destinatario tipico di questo modulo (capo
  reparto, manutenzione) è proprio chi il portale non lo apre: mandargli una
  mail per riga sarebbe il modo più rapido per farsi ignorare.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from checklist_operativa.models import ChiusuraEvento, ChiusuraVoce
from core.notifiche import invia_notifica

logger = logging.getLogger(__name__)

# Soglie di preavviso: notificato solo quando i giorni residui coincidono con
# una di queste, cosi' il comando puo' girare 1x/giorno senza spammare.
_SOGLIE_GIORNI = (7, 3, 1, 0)


def _destinatario(dipendente) -> str:
    """Indirizzo a cui scrivere.

    In ``anagrafica_dipendenti`` il campo ``email`` è l'identificativo di login
    legacy, **non** un recapito: le comunicazioni usano ``email_notifica``.
    """
    return (getattr(dipendente, "email_notifica", "") or "").strip()


class Command(BaseCommand):
    help = "Invia promemoria (in-app + email) ai responsabili di task non confermati per le chiusure in arrivo."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Mostra senza inviare nulla.")
        parser.add_argument(
            "--solo-notifiche", action="store_true",
            help="Salta le email e invia solo le notifiche in-app (comportamento storico).",
        )

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        solo_notifiche = bool(options.get("solo_notifiche"))
        oggi = timezone.localdate()

        eventi = ChiusuraEvento.objects.filter(
            stato=ChiusuraEvento.STATO_APERTA,
            data_inizio__gte=oggi,
        )

        inviati = 0
        email_inviate = 0
        for evento in eventi:
            giorni_residui = (evento.data_inizio - oggi).days
            if giorni_residui not in _SOGLIE_GIORNI:
                continue

            voci_da_confermare = (
                ChiusuraVoce.objects.filter(evento=evento, confermato=False, responsabile__isnull=False)
                .select_related("responsabile")
                .order_by("ordine", "id")
            )
            per_responsabile: dict[int, list] = defaultdict(list)
            for voce in voci_da_confermare:
                messaggio = (
                    f"Checklist chiusura '{evento.nome}' ({evento.data_inizio:%d/%m/%Y}): "
                    f"manca la conferma per '{voce.descrizione[:80]}'."
                )
                self.stdout.write(
                    f"[{'DRY-RUN ' if dry_run else ''}gg={giorni_residui}] "
                    f"{voce.responsabile} -> {messaggio}"
                )
                per_responsabile[voce.responsabile_id].append(voce)
                if not dry_run and voce.responsabile.utente_id:
                    invia_notifica(
                        voce.responsabile.utente_id,
                        "generico",
                        messaggio,
                        "/checklist-operativa/",
                    )
                    inviati += 1

            if solo_notifiche:
                continue
            for voci in per_responsabile.values():
                if self._invia_email(evento, voci, giorni_residui, dry_run=dry_run):
                    email_inviate += 1

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna notifica e nessuna email inviata."))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Notifiche inviate: {inviati} · Email inviate: {email_inviate}"
            ))

    def _invia_email(self, evento, voci: list, giorni_residui: int, *, dry_run: bool) -> bool:
        """Una email al responsabile con tutte le sue voci mancanti. True se inviata."""
        responsabile = voci[0].responsabile
        indirizzo = _destinatario(responsabile)
        if not indirizzo:
            self.stdout.write(f"  (nessun indirizzo per {responsabile}: solo notifica in-app)")
            return False
        if dry_run:
            self.stdout.write(f"  [DRY-RUN email] {indirizzo} ({len(voci)} voci)")
            return False

        quando = (
            "oggi" if giorni_residui == 0
            else "domani" if giorni_residui == 1
            else f"fra {giorni_residui} giorni"
        )
        elenco = "\n".join(f"- {voce.descrizione}" for voce in voci)
        subject = f"Checklist chiusura «{evento.nome}»: {len(voci)} da confermare"
        body = (
            f"La chiusura «{evento.nome}» comincia {quando} "
            f"({evento.data_inizio:%d/%m/%Y}).\n\n"
            f"Risultano ancora da confermare:\n{elenco}\n\n"
            "Le conferme si registrano dalla pagina Checklist Operativa del portale."
        )

        from core.email_utils import email_cta, send_hub_mail, text_to_html

        fragment = text_to_html(body)
        site_url = (getattr(settings, "SITE_URL", "") or "").rstrip("/")
        if site_url:
            fragment += email_cta("Apri la checklist", f"{site_url}/checklist-operativa/")

        try:
            send_hub_mail(
                subject, body, [indirizzo],
                email_type="Checklist Operativa",
                section_label="Promemoria chiusura aziendale",
                body_html_fragment=fragment,
                fail_silently=False,
            )
        except Exception:
            # L'email è un canale in più: se salta, la notifica in-app è già
            # partita e il comando deve completare gli altri destinatari.
            logger.exception("Checklist: invio email a %s fallito", indirizzo)
            return False
        return True
