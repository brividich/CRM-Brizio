"""AU51 - Digest mattutino per caporeparto (cross-modulo).

Job schedulato (NON regola del designer automazioni): da lanciare ogni mattina via
Task Scheduler di Windows.

Per ogni caporeparto invia un riepilogo del suo reparto:
  - assenze da approvare
  - ticket del reparto aperti
  - incidenti aperti
  - richieste DPI in attesa

STATO: SCAFFOLD. L'aggregazione "per caporeparto" e il legame capo<->reparto dipendono dalle
relazioni reali (Reparto.caporeparto_legacy_id e fonte ruoli CR/CC configurabile, vedi
tasks.TaskImpostazioni.roles_source). Le query per modulo sono lasciate come TODO espliciti
perche' vanno verificate sul DB reale prima di abilitare l'invio. Eseguibile in --dry-run per
sviluppare l'aggregazione senza inviare nulla.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "AU51 - Digest mattutino per caporeparto (assenze/ticket/incidenti/DPI del reparto)."

    def add_arguments(self, parser):
        parser.add_argument("--recipients", nargs="*", help="Limita/forza i destinatari (email caporeparto).")
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare email.")

    def handle(self, *args, **options):
        today = timezone.localdate()
        dry_run = bool(options.get("dry_run"))

        # ── 1. Risolvere l'elenco caporeparto e il loro reparto ───────────────────────
        # TODO: caricare i capireparto dalla fonte autorevole (Reparto.caporeparto_legacy_id;
        #       email via anagrafica). Vedi feedback memory: la fonte è Reparto, non il campo
        #       denormalizzato DipendenteAnagraficaAziendale.caporeparto_legacy_id.
        capi: list[dict] = []  # es. [{"email": "...", "reparto": "...", "legacy_id": 123}, ...]

        if not capi:
            self.stdout.write(self.style.WARNING(
                "AU51 SCAFFOLD: elenco capireparto non ancora implementato. "
                "Completare il caricamento capi<->reparto prima di schedulare."
            ))
            if not dry_run:
                return

        from core.email_utils import send_hub_mail
        sent = 0
        for capo in capi:
            reparto = capo.get("reparto")
            # ── 2. Aggregare i contenuti del reparto (TODO query reali) ───────────────
            # assenze_da_approvare = Assenza.objects.filter(... reparto=reparto, moderation_status=PENDING)
            # ticket_reparto       = Ticket.objects.filter(... reparto/asset reparto, stato aperto)
            # incidenti_aperti     = RilevazioneIncidente.objects.filter(reparto=reparto, chiusura_rspp=False)
            # dpi_in_attesa        = RichiestaDPI.objects.filter(richiedente_reparto=reparto, stato=INVIATA)
            lines = [
                f"NOVICROM HUB - Buongiorno, riepilogo reparto {reparto} ({today:%d/%m/%Y})",
                "=" * 60,
                "  (sezioni da popolare: assenze da approvare, ticket reparto, incidenti aperti, DPI in attesa)",
            ]
            body = "\n".join(lines)
            subject = f"[Caporeparto] Riepilogo {reparto} - {today:%d/%m/%Y}"
            if dry_run:
                self.stdout.write(self.style.WARNING(f"[DRY-RUN] -> {capo.get('email')}"))
                self.stdout.write(body)
                continue
            send_hub_mail(
                subject, body, [capo.get("email")],
                email_type="Core", section_label="Digest caporeparto", fail_silently=True,
            )
            sent += 1

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"Digest caporeparto inviato a {sent} destinatari."))
