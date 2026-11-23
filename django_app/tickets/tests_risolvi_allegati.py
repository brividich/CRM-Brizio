"""«Risolvi» con allegati (foto, screenshot, rapportino): tutto o niente. Solo dati sintetici."""
import shutil
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from core.upload_mime import UploadMimeValidationError
from tickets.allegati import DESCRIZIONE_RISOLUZIONE, tipo_documento_per_mime
from tickets.models import StatoTicket, StatoValidazioneAllegato, TicketAllegato, TicketCommento
from tickets.tests_lavorazione import LavorazioneBase

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _png(nome="screenshot-sintetico.png"):
    return SimpleUploadedFile(nome, _PNG, content_type="image/png")


class RisolviConAllegatiTests(LavorazioneBase):
    def setUp(self):
        super().setUp()
        root = Path.cwd() / ".tmp_tests" / f"tickets-risolvi-{uuid4().hex}"
        root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        override = override_settings(TICKETS_PRIVATE_ROOT=root, MEDIA_ROOT=root)
        override.enable()
        self.addCleanup(override.disable)
        # libmagic non serve nei test: il controllo del MIME reale ha già i suoi.
        for dove in ("core.upload_mime.validate_extension_and_mime", "tickets.allegati.validate_extension_and_mime"):
            p = patch(dove, return_value="image/png")
            p.start()
            self.addCleanup(p.stop)

    def _risolvi(self, ticket, files, **extra):
        dati = {"ticket_id": ticket.pk, "azione": "risolvi", "intervento_svolto": "Sostituito fusibile sintetico",
                "ricorrente": "", **extra}
        if files:
            dati["file"] = files
        return self.client.post(reverse("tickets:api_stato"), data=dati)

    def test_risolve_e_salva_gli_allegati_gia_validati(self):
        ticket = self._ticket(richiedente_email="richiedente@example.com")
        with self.captureOnCommitCallbacks(execute=True):
            response = self._risolvi(ticket, [_png(), _png("seconda.png")])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["allegati"], 2)
        ticket.refresh_from_db()
        self.assertEqual(ticket.stato, StatoTicket.RISOLTO)
        allegati = TicketAllegato.objects.filter(ticket=ticket)
        self.assertEqual(allegati.count(), 2)
        for a in allegati:
            self.assertEqual(a.stato_validazione, StatoValidazioneAllegato.VALIDATO)
            self.assertEqual(a.descrizione, DESCRIZIONE_RISOLUZIONE)
            self.assertEqual(a.tipo_documento, "FOTO")
        self.assertTrue(TicketCommento.objects.filter(ticket=ticket, testo__contains="ha caricato 2 allegati").exists())
        conferme = [m for m in mail.outbox if "richiedente@example.com" in m.to]
        self.assertEqual(len(conferme), 1)
        self.assertIn("2 allegati della risoluzione", conferme[0].body)

    def test_allegato_rifiutato_non_risolve_niente(self):
        ticket = self._ticket(stato=StatoTicket.IN_CARICO)
        with patch("core.upload_mime.validate_extension_and_mime",
                   side_effect=UploadMimeValidationError("x.exe: formato non consentito (.exe).")):
            response = self._risolvi(ticket, [SimpleUploadedFile("x.exe", b"MZ")])
        self.assertEqual(response.status_code, 400)
        self.assertIn("ticket non risolto", response.json()["error"])
        ticket.refresh_from_db()
        self.assertEqual(ticket.stato, StatoTicket.IN_CARICO)
        self.assertFalse(TicketAllegato.objects.filter(ticket=ticket).exists())

    def test_massimo_dieci_file(self):
        ticket = self._ticket()
        response = self._risolvi(ticket, [_png(f"f{i}.png") for i in range(11)])
        self.assertEqual(response.status_code, 400)
        ticket.refresh_from_db()
        self.assertEqual(ticket.stato, StatoTicket.APERTA)

    def test_lavoro_mancante_non_salva_i_file(self):
        ticket = self._ticket()
        response = self._risolvi(ticket, [_png()], intervento_svolto="  ")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(TicketAllegato.objects.filter(ticket=ticket).exists())

    def test_senza_allegati_la_mail_non_ne_parla(self):
        ticket = self._ticket(richiedente_email="richiedente@example.com")
        with self.captureOnCommitCallbacks(execute=True):
            self._risolvi(ticket, [])
        conferme = [m for m in mail.outbox if "richiedente@example.com" in m.to]
        self.assertEqual(len(conferme), 1)
        self.assertNotIn("allegat", conferme[0].body)

    def test_file_solo_con_risolvi(self):
        ticket = self._ticket()
        response = self.client.post(reverse("tickets:api_stato"),
                                    data={"ticket_id": ticket.pk, "stato": "IN_ATTESA", "file": [_png()]})
        self.assertEqual(response.status_code, 400)

    def test_scheda_mostra_l_area_allegati_nel_pannello(self):
        ticket = self._ticket()
        response = self.client.get(reverse("tickets:gestione_detail", args=[ticket.pk]) + "?azione=risolvi")
        self.assertContains(response, 'id="rv-allegati"')
        self.assertContains(response, "Ctrl+V incolla uno screenshot")

    def test_tipo_documento_dal_mime(self):
        self.assertEqual(tipo_documento_per_mime("image/jpeg"), "FOTO")
        self.assertEqual(tipo_documento_per_mime("application/pdf"), "RAPPORTINO")
        self.assertEqual(tipo_documento_per_mime("text/plain"), "ALTRO")
