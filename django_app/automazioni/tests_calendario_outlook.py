"""«Aggiungi al calendario Outlook» nelle mail delle assenze."""
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from django.core import mail
from django.test import SimpleTestCase, override_settings

from . import calendario_outlook as co
from .approval_email_templates import render_approval_email
from .services import _send_approval_email


def _payload(**kw):
    base = {"id": 7, "dipendente_nome": "ROSSI MARIO", "tipo_assenza": "Ferie",
            "data_inizio": datetime(2026, 10, 26), "data_fine": datetime(2026, 10, 30, 23, 59),
            "moderation_status": 2}
    base.update(kw)
    return base


class EventoTests(SimpleTestCase):
    def test_solo_per_le_assenze_non_rifiutate(self):
        self.assertIsNone(co.evento_assenza("tickets", _payload()))
        self.assertIsNone(co.evento_assenza("assenze", _payload(moderation_status=1)))
        self.assertIsNone(co.evento_assenza("assenze", _payload(data_inizio="")))
        self.assertEqual(co.evento_assenza("assenze", _payload())["titolo"], "Ferie: ROSSI MARIO")

    def test_link_giornata_intera_con_fine_esclusa(self):
        q = parse_qs(urlparse(co.link_outlook(co.evento_assenza("assenze", _payload()))).query)
        self.assertEqual((q["startdt"][0], q["enddt"][0], q["allday"][0]), ("2026-10-26", "2026-10-31", "true"))

    def test_permesso_con_orari_e_date_testo(self):
        ev = co.evento_assenza("assenze", _payload(tipo_assenza="Permesso", data_inizio="2026-10-27T08:00:00",
                                                   data_fine="2026-10-27 12:30:00"))
        self.assertFalse(ev["giornata_intera"])
        q = parse_qs(urlparse(co.link_outlook(ev)).query)
        self.assertEqual(q["startdt"][0], "2026-10-27T08:00:00")
        self.assertIn("DTSTART:20261027T070000Z", co.ics(ev).decode())  # 27/10: ora solare, UTC+1

    def test_ics_evento_libero(self):
        testo = co.ics(co.evento_assenza("assenze", _payload())).decode()
        self.assertIn("DTSTART;VALUE=DATE:20261026", testo)
        self.assertIn("DTEND;VALUE=DATE:20261031", testo)
        self.assertIn("TRANSP:TRANSPARENT", testo)
        self.assertIn("X-MICROSOFT-CDO-BUSYSTATUS:FREE", testo)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   DEFAULT_FROM_EMAIL="noreply@example.com")
class MailApprovazioneTests(SimpleTestCase):
    def test_pulsante_e_allegato(self):
        ev = co.evento_assenza("assenze", _payload())
        _send_approval_email(approver_emails=["capo@example.com"], subject="Ferie", message_body="Richiesta",
                             approve_url="https://x/ok", reject_url="https://x/no", approve_label="Approva",
                             reject_label="Rifiuta", expires_at=None, calendar_event=ev)
        msg = mail.outbox[0]
        self.assertIn(co.ETICHETTA, msg.alternatives[0][0])
        self.assertIn("outlook.office.com", msg.body)
        nome, contenuto, tipo = msg.attachments[0]
        self.assertEqual(nome, "assenza.ics")
        self.assertTrue(tipo.startswith("text/calendar"))

    def test_senza_evento_nessun_allegato(self):
        _send_approval_email(approver_emails=["capo@example.com"], subject="X", message_body="Y",
                             approve_url="https://x/ok", reject_url="https://x/no", approve_label="Approva",
                             reject_label="Rifiuta", expires_at=None)
        self.assertEqual(mail.outbox[0].attachments, [])
        self.assertNotIn(co.ETICHETTA, mail.outbox[0].alternatives[0][0])

    def test_template_approvazione_accetta_pulsante_extra(self):
        class Tpl:
            subject_template = "S"
            approval_label = rejection_label = ""
            title_template = intro_template = body_template = facts_lines = ""
            include_facts = include_mailto_actions = False
            section_label = email_type_label = ""

            def uses_portal_links(self):
                return True

            def uses_mailto(self):
                return False

        out = render_approval_email(Tpl(), {}, approve_url="https://x/ok", reject_url="https://x/no",
                                    extra_cta_html="<a>EXTRA</a>", extra_cta_text="EXTRA: link")
        self.assertIn("<a>EXTRA</a>", out["html_body"])
        self.assertIn("EXTRA: link", out["text_body"])
