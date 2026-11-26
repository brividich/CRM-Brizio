"""Promemoria micro-corsi e-learning ancora da completare.

1. **Scaletta** (``services.elearning_promemoria``): promemoria prima della
   scadenza, solleciti dopo la scadenza al dipendente e al suo responsabile,
   digest settimanale al responsabile; ogni avviso parte una volta sola.
2. **Digest HR** di tutte le iscrizioni non completate. Pattern speculare a ``send_visite_expiry_reminders`` /
``send_visite_mediche_digest``. Schedulare via QCluster (intervalli in MINUTI).

Destinatari digest: override CLI → SiteConfig ``elearning_reminder_emails`` →
ADMINS → superuser. Notifica in-app sempre al discente (rispetta gli interruttori).
"""
from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.utils import timezone

from anagrafica.services.elearning_notifications import iter_corsi_da_completare, quiz_da_abbinare_per_corso
from anagrafica.services.email_digest import digest_fragment
from anagrafica.services.reminders import get_reminder_recipients

_STATO_LABEL = {"ISCRITTO": "Iscritto", "IN_CORSO": "In corso", "NON_SUPERATO": "Non superato"}


class Command(BaseCommand):
    help = "Promemoria e digest dei micro-corsi e-learning non ancora completati."

    def add_arguments(self, parser):
        parser.add_argument(
            "--recipients", nargs="*",
            help="Email destinatari del digest (sovrascrive SiteConfig/ADMINS).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare.")

    def handle(self, *args, **options):
        today = timezone.localdate()
        dry_run = bool(options.get("dry_run"))
        recipients = get_reminder_recipients("elearning_reminder_emails", options.get("recipients") or [])

        # Stato automatico delle edizioni («Pianificata» → «In corso» il giorno d'inizio)
        # prima della scaletta: promemoria e solleciti leggono lo stato già aggiornato.
        if not dry_run:
            from anagrafica.services.formazione_aula import aggiorna_stati
            n_st = aggiorna_stati(today)
            if n_st:
                self.stdout.write(f"Edizioni passate a «In corso»: {n_st}.")

        from anagrafica.services.elearning_promemoria import esegui
        rie = esegui(oggi=today, invia=not dry_run)
        self.stdout.write(
            f"Scaletta: {rie.promemoria} promemoria, {rie.solleciti} solleciti, "
            f"{rie.email_responsabili} email ai responsabili, {rie.digest} digest settimanali"
            + (f", {len(set(rie.senza_responsabile))} persone senza responsabile" if rie.senza_responsabile else "")
            + (" [DRY-RUN]" if dry_run else "") + "."
        )

        # Lezioni online delle sessioni: promemoria N giorni prima della scadenza.
        if not dry_run:
            from anagrafica.services.sessione_online import promemoria_in_scadenza
            try:
                n_so = promemoria_in_scadenza(today)
                self.stdout.write(f"Lezioni online di sessione: {n_so} promemoria.")
            except Exception as exc:  # non deve fermare il resto dei promemoria
                self.stderr.write(f"Promemoria lezioni online non inviati: {exc}")

        iscrizioni = list(iter_corsi_da_completare())
        da_abbinare = quiz_da_abbinare_per_corso()
        if not iscrizioni and not da_abbinare:
            self.stdout.write("Nessun micro-corso e-learning da completare.")
            return
        nomi = {}
        if iscrizioni:
            from anagrafica.views._helpers import _build_nomi_map
            nomi = _build_nomi_map()

        def _nome(lid):
            return nomi.get(lid) or f"Dipendente #{lid}"

        per_corso: dict[str, list] = defaultdict(list)
        lines = [
            f"NOVICROM HUB - Promemoria micro-corsi e-learning del {today:%d-%m-%Y}",
            "=" * 60,
            "",
            f"Iscrizioni ancora da completare: {len(iscrizioni)}",
            "",
        ]
        if da_abbinare:
            lines.append(f"Quiz superati dal link aperto da abbinare: {sum(n for _t, n in da_abbinare)}")
            lines += [f"  {titolo}: {n}" for titolo, n in da_abbinare]
            lines.append("")
        for iscr in iscrizioni:
            per_corso[iscr.corso.titolo].append(iscr)
            lines.append(
                f"  [{_STATO_LABEL.get(iscr.stato, iscr.stato)}] {_nome(iscr.legacy_anagrafica_id)}"
                f" - {iscr.corso.codice} {iscr.corso.titolo}"
            )
            # Niente più notifica quotidiana a ogni discente: la manda la scaletta.

        body = "\n".join(lines)
        subject = f"[E-LEARNING] {len(iscrizioni)} corsi da completare - {today:%d-%m-%Y}"
        if da_abbinare:
            subject += f" · {sum(n for _t, n in da_abbinare)} quiz da abbinare"

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna email/notifica inviata."))
            self.stdout.write(f"Destinatari: {recipients}")
            self.stdout.write(body)
            return

        if not recipients:
            self.stdout.write(self.style.ERROR(
                "Nessun destinatario configurato (SiteConfig 'elearning_reminder_emails' / ADMINS vuoti)."
                " Scaletta dei promemoria eseguita comunque."
            ))
            return

        sezioni = []
        if da_abbinare:
            sezioni.append((f"Quiz superati dal link aperto da abbinare ({sum(n for _t, n in da_abbinare)})", [{
                "title": titolo, "subtitle": f"{n} da abbinare",
                "note": "Apri il corso online, scheda «Link aperto», e abbina la persona.",
                "accent": "#d97706",
            } for titolo, n in da_abbinare]))
        for titolo, iscr_list in sorted(per_corso.items()):
            cards = [{
                "title": _nome(iscr.legacy_anagrafica_id),
                "subtitle": f"{iscr.corso.codice} · {_STATO_LABEL.get(iscr.stato, iscr.stato)}",
                "note": (f"Avanzamento slide {iscr.ultima_slide_ordine}/{iscr.n_slide_totali}"
                         if iscr.n_slide_totali else ""),
                "accent": "#2563eb",
            } for iscr in iscr_list]
            sezioni.append((f"{titolo} ({len(iscr_list)})", cards))
        fragment = digest_fragment(sezioni)

        from automazioni.mail_config import apply_mail_overrides
        from core.email_utils import send_hub_mail
        subject, body, fragment, footer = apply_mail_overrides(
            "elearning_reminders", subject=subject, body_text=body, fragment=fragment)
        send_hub_mail(
            subject, body, recipients,
            email_type="Anagrafica HR",
            section_label="Reminder e-learning",
            body_html_fragment=fragment,
            footer_note=footer,
            fail_silently=False,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Email inviata a {len(recipients)} destinatari. Iscrizioni da completare: {len(iscrizioni)}."
            + (f" Quiz da abbinare: {sum(n for _t, n in da_abbinare)}." if da_abbinare else "")
        ))
