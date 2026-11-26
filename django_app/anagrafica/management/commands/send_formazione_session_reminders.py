"""Promemoria per le sessioni formative imminenti (T-7 e T-1 per default).

Per ogni edizione **pianificata** che inizia tra i giorni di anticipo indicati,
invia a ciascun iscritto (non ritirato/completato) una notifica nel portale.
**Nessuna email ai partecipanti** (decisione del 25/11/2026): la mail la manda
l'azienda. Errori sul singolo invio non bloccano gli altri.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone

from django.core.management.base import BaseCommand
from django.utils import timezone


def _build_ics(sess) -> str:
    """Genera un VEVENT minimale per l'edizione (orario dalla prima lezione, se c'è)."""
    lez = sess.lezioni.order_by("data", "ora_inizio").first()
    if lez:
        dt_s = datetime.combine(lez.data, lez.ora_inizio).strftime("%Y%m%dT%H%M%S")
        dt_e = datetime.combine(lez.data, lez.ora_fine).strftime("%Y%m%dT%H%M%S")
        dt_fmt = ""
    else:
        dt_s = sess.data_inizio.strftime("%Y%m%d")
        dt_e = (sess.data_fine + timedelta(days=1)).strftime("%Y%m%d")
        dt_fmt = ";VALUE=DATE"
    # utcnow() e' deprecato da Python 3.12 e restituisce un datetime naive:
    # timezone.now() e' gia' aware, e la "Z" resta corretta convertendo a UTC.
    stamp = timezone.now().astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def esc(s: str) -> str:
        return (s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", " ")

    loc = esc(sess.sede or sess.get_modalita_display() or "")
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//NOVICROM HUB//Formazione//IT",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "BEGIN:VEVENT", f"UID:formazione-{sess.pk}@novicromhub", f"DTSTAMP:{stamp}",
        f"DTSTART{dt_fmt}:{dt_s}", f"DTEND{dt_fmt}:{dt_e}",
        f"SUMMARY:{esc('Corso: ' + sess.corso.titolo)}",
        f"LOCATION:{loc}",
        f"DESCRIPTION:{esc('Edizione ' + sess.codice_sessione)}",
        "END:VEVENT", "END:VCALENDAR",
    ])


def _url_mie_attivita() -> str:
    from django.urls import NoReverseMatch, reverse
    try:
        return reverse("mie_attivita")
    except NoReverseMatch:
        return "/mie-attivita"


def testo_e_link(sess, quando: str) -> tuple[str, str]:
    """(testo, link) del promemoria. Online (slide + test): il player della lezione e il
    periodo in cui è disponibile; in aula: «Le mie attività» del partecipante (non la
    pagina iscritti, che è di chi gestisce la formazione)."""
    if sess.modalita == "ONLINE":
        from anagrafica.services.formazione_aula import scadenza_online
        from anagrafica.services.sessione_online import _url_lezione, config
        cfg = config(sess)
        dal = (cfg.disponibile_dal if cfg and cfg.disponibile_dal else None) or sess.data_inizio
        entro = scadenza_online(sess)
        testo = f"Lezione online «{sess.corso.titolo}»: disponibile dal {dal:%d-%m-%Y}"
        if entro:
            testo += f" entro il {entro:%d-%m-%Y}"
        return testo + ".", _url_lezione(sess)
    return f"Promemoria: corso «{sess.corso.titolo}» il {quando}.", _url_mie_attivita()


class Command(BaseCommand):
    help = "Promemoria nel portale (nessuna email) per le sessioni formative imminenti."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", nargs="*", type=int, default=[7, 1],
            help="Giorni di anticipo (default: 7 e 1).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare.")

    def handle(self, *args, **options):
        from core.notifiche import invia_notifica
        from core.permessi.identita import utente_da_anagrafica
        from anagrafica.models_formazione import TrainingEnrollment, TrainingSession

        today = timezone.localdate()
        giorni = sorted({int(d) for d in (options.get("days") or [7, 1]) if int(d) >= 0}) or [7, 1]
        dry = bool(options.get("dry_run"))
        target = {today + timedelta(days=d): d for d in giorni}

        sessioni = list(
            TrainingSession.objects
            .filter(stato="PIANIFICATA", data_inizio__in=list(target))
            .select_related("corso")
        )
        if not sessioni:
            self.stdout.write("Nessuna sessione imminente da notificare.")
            return

        n_notif = 0
        for sess in sessioni:
            gg = target.get(sess.data_inizio)
            iscritti = list(
                TrainingEnrollment.objects
                .filter(sessione=sess)
                .exclude(stato__in=("RITIRATO", "COMPLETATO"))
            )
            ids = [i.legacy_anagrafica_id for i in iscritti]
            if not ids:
                continue
            quando = f"{sess.data_inizio:%d-%m-%Y}" + (f" (tra {gg} giorni)" if gg else "")
            testo, link = testo_e_link(sess, quando)
            # Solo notifica nel portale: ai partecipanti non partono email (25/11/2026,
            # la comunicazione via mail la manda l'azienda, una sola).
            for i in iscritti:
                if not dry:
                    try:
                        invia_notifica(
                            utente_da_anagrafica(i.legacy_anagrafica_id), "formazione_promemoria",
                            testo, link,
                        )
                    except Exception:
                        pass
                n_notif += 1

        if dry:
            self.stdout.write(self.style.WARNING(
                f"[DRY-RUN] {len(sessioni)} sessioni, {n_notif} notifiche previste (nessuna email)."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Promemoria nel portale: {n_notif} notifiche ({len(sessioni)} sessioni). Nessuna email."
            ))
