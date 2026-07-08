"""Promemoria per le sessioni formative imminenti (T-7 e T-1 per default).

Per ogni edizione **pianificata** che inizia tra i giorni di anticipo indicati,
invia a ciascun iscritto (non ritirato/completato) un promemoria email con
**invito calendario allegato (.ics)** e una notifica in-app. Riduce i no-show.

Fail-safe: se un iscritto non ha email di notifica riceve solo la notifica in-app;
errori sul singolo invio non bloccano gli altri.
"""
from __future__ import annotations

from datetime import datetime, timedelta

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
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

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


class Command(BaseCommand):
    help = "Promemoria email + invito calendario (.ics) per le sessioni formative imminenti."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", nargs="*", type=int, default=[7, 1],
            help="Giorni di anticipo (default: 7 e 1).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare.")

    def handle(self, *args, **options):
        from core.legacy_anagrafica import fetch_anagrafica_rows
        from core.notifiche import invia_notifica
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

        n_mail = n_notif = 0
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
            rows = {}
            try:
                rows = {int(r["id"]): r for r in fetch_anagrafica_rows(ids=ids) if r.get("id")}
            except Exception:
                pass

            ics = _build_ics(sess)
            quando = f"{sess.data_inizio:%d-%m-%Y}" + (f" (tra {gg} giorni)" if gg else "")
            subject = f"Promemoria corso: {sess.corso.titolo} il {sess.data_inizio:%d-%m-%Y}"
            body = (
                f"Ti ricordiamo il corso «{sess.corso.titolo}» — edizione {sess.codice_sessione}.\n\n"
                f"Inizio: {quando}\n"
                f"Sede / modalità: {sess.sede or '-'} ({sess.get_modalita_display()})\n"
                f"{('Docente: ' + sess.docente_nome) if sess.docente_nome else ''}\n\n"
                f"Trovi l'invito da aggiungere al calendario in allegato (.ics)."
            )

            for i in iscritti:
                if not dry:
                    try:
                        invia_notifica(
                            i.legacy_anagrafica_id, "formazione_promemoria",
                            f"Promemoria: corso «{sess.corso.titolo}» il {sess.data_inizio:%d-%m-%Y}.",
                            f"/anagrafica/formazione/sessioni/{sess.pk}/iscritti/",
                        )
                        n_notif += 1
                    except Exception:
                        pass
                email = (rows.get(i.legacy_anagrafica_id, {}).get("email_notifica") or "").strip()
                from core.notifiche_prefs import should_notify
                if email and should_notify(tipo="formazione_promemoria", legacy_user_id=i.legacy_anagrafica_id):
                    if not dry:
                        from core.email_utils import send_hub_mail
                        try:
                            send_hub_mail(
                                subject, body, [email],
                                email_type="Anagrafica HR",
                                section_label="Promemoria corso",
                                attachments=[(f"corso_{sess.codice_sessione}.ics", ics, "text/calendar")],
                                fail_silently=True,
                            )
                        except Exception:
                            pass
                    n_mail += 1

        if dry:
            self.stdout.write(self.style.WARNING(
                f"[DRY-RUN] {len(sessioni)} sessioni, {n_mail} email previste, {n_notif} notifiche."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Promemoria inviati: {n_mail} email, {n_notif} notifiche ({len(sessioni)} sessioni)."
            ))
