"""«Aggiungi al calendario Outlook» nelle mail delle assenze."""
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings

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

    def test_pulsante_solo_se_il_capo_e_fra_i_destinatari(self):
        payload = _payload(capo_email="Capo@Example.com")
        self.assertTrue(co.per_il_capo(payload, ["assenze@example.com", "capo@example.com"]))
        self.assertFalse(co.per_il_capo(payload, ["assenze@example.com"]))
        self.assertFalse(co.per_il_capo(_payload(), ["assenze@example.com"]))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   DEFAULT_FROM_EMAIL="noreply@example.com")
class MailApprovazioneTests(SimpleTestCase):
    def test_pulsante_senza_allegato(self):
        ev = co.evento_assenza("assenze", _payload())
        _send_approval_email(approver_emails=["capo@example.com"], subject="Ferie", message_body="Richiesta",
                             approve_url="https://x/ok", reject_url="https://x/no", approve_label="Approva",
                             reject_label="Rifiuta", expires_at=None, calendar_event=ev)
        msg = mail.outbox[0]
        self.assertIn(co.ETICHETTA, msg.alternatives[0][0])
        self.assertIn("outlook.office.com", msg.body)
        self.assertEqual(msg.attachments, [])

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

    def test_template_approvazione_mette_il_riquadro_della_serie_in_testa(self):
        class Tpl:
            subject_template = "S"
            approval_label = rejection_label = ""
            title_template = body_template = facts_lines = ""
            intro_template = "Richiesta di permesso"
            include_facts = include_mailto_actions = False
            section_label = email_type_label = ""

            def uses_portal_links(self):
                return True

            def uses_mailto(self):
                return False

        out = render_approval_email(Tpl(), {}, approve_url="https://x/ok", reject_url="https://x/no",
                                    extra_body_html="<p>SERIE</p>", extra_body_text="SERIE dal al\n\n")
        self.assertLess(out["html_body"].index("<p>SERIE</p>"), out["html_body"].index("Richiesta di permesso"))
        self.assertLess(out["text_body"].index("SERIE dal al"), out["text_body"].index("Richiesta di permesso"))


class SerieInTestaTests(SimpleTestCase):
    def test_riquadro_dopo_body_o_in_testa_al_frammento(self):
        from .services import _inserisci_in_testa_html

        self.assertEqual(_inserisci_in_testa_html("<p>x</p>", "<b>S</b>"), "<b>S</b><p>x</p>")
        self.assertEqual(_inserisci_in_testa_html("<html><body class='a'><p>x</p>", "<b>S</b>"),
                         "<html><body class='a'><b>S</b><p>x</p>")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   DEFAULT_FROM_EMAIL="noreply@example.com")
class MailApprovaECalendarioTests(SimpleTestCase):
    def test_terzo_pulsante_con_spunta_gia_messa(self):
        _send_approval_email(approver_emails=["capo@example.com"], subject="Ferie", message_body="Richiesta",
                             approve_url="https://x/r/abc/approva/", reject_url="https://x/r/abc/rifiuta/",
                             approve_label="Approva", reject_label="Rifiuta", expires_at=None, calendar_opt_in=True)
        msg = mail.outbox[0]
        self.assertIn(co.ETICHETTA_APPROVA, msg.alternatives[0][0])
        self.assertIn("https://x/r/abc/approva/?calendario=1", msg.alternatives[0][0])
        self.assertIn(f"{co.ETICHETTA_APPROVA}: https://x/r/abc/approva/?calendario=1", msg.body)
        self.assertNotIn("outlook.office.com", msg.body)


class ConfermaConCalendarioTests(TestCase):
    """Pagina del link personale: la spunta registra il calendario di chi ha ricevuto il link."""

    def setUp(self):
        from assenze.models import AssenzeImpostazioniHR

        imp = AssenzeImpostazioniHR.get_solo()
        imp.outlook_capo_attivo, imp.outlook_capo_modo = True, "richiesta"
        imp.save()

    def _link(self):
        from .tests_approval_links import _approval, _rule
        from .approval_links import create_link

        self.n = getattr(self, "n", 0) + 1
        approval = _approval(_rule(f"test-calendario-{self.n}"), resume_payload={"id": 4321, "tipo_assenza": "Ferie"})
        return create_link(approval, "car.sintetico@example.com")

    def test_get_con_calendario_mostra_la_spunta_messa(self):
        raw = self._link()
        resp = self.client.get(f"/approval-actions/r/{raw}/approva/?calendario=1")
        self.assertContains(resp, 'name="calendario" value="1" form="approval-decision-form" checked')
        self.assertNotContains(self.client.get(f"/approval-actions/r/{self._link()}/rifiuta/"), 'name="calendario"')

    def test_post_con_spunta_usa_la_casella_del_link(self):
        from assenze.models import AssenzaOutlook

        raw = self._link()
        resp = self.client.post(f"/approval-actions/r/{raw}/approva/", {"calendario": "1"})
        self.assertEqual(resp.status_code, 302)
        self.assertIn("calendario=1", resp["Location"])
        self.assertEqual(list(AssenzaOutlook.objects.values_list("assenza_id", "email")),
                         [(4321, "car.sintetico@example.com")])

    def test_post_senza_spunta_niente_calendario(self):
        from assenze.models import AssenzaOutlook

        raw = self._link()
        self.client.post(f"/approval-actions/r/{raw}/approva/")
        self.assertFalse(AssenzaOutlook.objects.exists())
