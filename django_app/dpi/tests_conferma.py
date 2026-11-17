"""Conferma di ricevuta senza badge: nessuna mail, «Da confermare» e conferma automatica
dopo 24 ore; i link delle mail inviate prima del 17/11/2026 valgono finché è in attesa."""

from __future__ import annotations

import secrets
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import conferme, tasks
from .models import (
    CategoriaDPI,
    ConfermaConsegnaDPI,
    DPIImpostazioni,
    LinkConfermaDPI,
    ModelloDPI,
    RichiestaDPI,
    StatoRichiesta,
    TipoDPI,
)

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False,
                   EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", SITE_URL="https://hub.example.test")
class ConfermaRicevutaTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="dpi-conf", password="x", email="c@y.z")
        self.client.force_login(self.admin)
        cat = CategoriaDPI.objects.create(nome="Mani", icona_emoji="gloves")
        self.modello = ModelloDPI.objects.create(tipo=TipoDPI.objects.create(categoria=cat, nome="Guanti"),
                                                 codice="GT-1", nome="Blade Safe")
        impost = DPIImpostazioni.get_singleton()
        impost.magazzino_emails = "magazzino@azienda.test"
        impost.save()
        p = mock.patch("dpi.pdf.render_modulo_consegna_dpi", return_value=b"%PDF")
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch("dpi.flusso._email_persona", return_value="mario.rossi@azienda.test")
        p.start()
        self.addCleanup(p.stop)

    def _richiesta(self, legacy=101, nome="Mario Rossi"):
        return RichiestaDPI.objects.create(
            categoria=self.modello.tipo.categoria, tipo_dpi=self.modello.tipo, modello_dpi=self.modello,
            stato=StatoRichiesta.APPROVATA, richiedente_nome=nome, richiedente_legacy_id=legacy,
        )

    def _consegna_banco(self, *richieste, **extra):
        mail.outbox.clear()
        return self.client.post(reverse("dpi:banco"), {
            "azione": "consegna", "ids": [r.pk for r in richieste], "data_consegna": "2026-11-02", **extra,
        })

    def _mail_conferma(self):
        return [m for m in mail.outbox if "ricevuta" in m.subject.lower()]

    def test_senza_badge_conferma_da_confermare_e_nessuna_mail(self):
        a, b = self._richiesta(), self._richiesta()
        self._consegna_banco(a, b)
        conferma = ConfermaConsegnaDPI.objects.get()
        self.assertEqual(conferma.stato, ConfermaConsegnaDPI.Stato.IN_ATTESA)
        self.assertEqual(conferma.consegne.count(), 2)
        self.assertEqual(self._mail_conferma(), [])
        self.assertFalse(LinkConfermaDPI.objects.exists())
        a.refresh_from_db()
        self.assertEqual(a.stato, StatoRichiesta.CONSEGNATA)  # la consegna vale subito

    def test_con_firma_o_carta_nessuna_conferma(self):
        self._consegna_banco(self._richiesta(), firmato_ricevuta="1")
        self.assertFalse(ConfermaConsegnaDPI.objects.exists())

    def test_consegna_dalla_scheda_apre_la_conferma(self):
        r = self._richiesta()
        self.client.post(reverse("dpi:consegna", args=[r.pk]), {"data_consegna": "2026-11-02"})
        self.assertEqual(ConfermaConsegnaDPI.objects.get().consegne.get().richiesta_id, r.pk)
        self.assertEqual(self._mail_conferma(), [])

    def test_autoconferma_dopo_24_ore(self):
        r = self._richiesta()
        self._consegna_banco(r)
        conferma = ConfermaConsegnaDPI.objects.get()
        self.assertEqual(conferme.autoconferma(), 0)  # non ancora
        self.assertEqual(conferme.autoconferma(adesso=conferma.created_at + timedelta(hours=23, minutes=59)), 0)
        self.assertEqual(conferme.autoconferma(adesso=conferma.created_at + timedelta(hours=24)), 1)
        self.assertEqual(conferme.autoconferma(adesso=conferma.created_at + timedelta(hours=25)), 0)  # una volta sola
        conferma.refresh_from_db()
        self.assertEqual((conferma.stato, conferma.decisa_da_email), (ConfermaConsegnaDPI.Stato.CONFERMATA, ""))
        self.assertIn("automaticamente", r.commenti.get().testo)

    def test_il_task_ogni_5_minuti_autoconferma(self):
        self._consegna_banco(self._richiesta())
        ConfermaConsegnaDPI.objects.update(created_at=timezone.now() - timedelta(hours=25))
        self.assertEqual(tasks.run_dpi_avvisi_consegna()["autoconfermate"], 1)

    def test_banco_mostra_quando_si_conferma_da_sola(self):
        self._consegna_banco(self._richiesta())
        pagina = self.client.get(reverse("dpi:banco"))
        self.assertContains(pagina, "si conferma da sola il")
        self.assertContains(pagina, "Consegna senza badge")
        self.assertNotContains(pagina, "Consegna con mail")

    def _link_vecchio(self, conferma):
        raw = secrets.token_urlsafe(32)
        LinkConfermaDPI.objects.create(conferma=conferma, email="mario.rossi@azienda.test", token_hash=conferme.hash_token(raw))
        return f"/approval-actions/dpi/{raw}/"

    def test_link_di_una_vecchia_mail_vale_finche_in_attesa(self):
        self._consegna_banco(self._richiesta())
        base = self._link_vecchio(ConfermaConsegnaDPI.objects.get())
        self.client.logout()
        mail.outbox.clear()
        self.client.post(base + "contesta/", {"nota": "mancano i guanti"})
        conferma = ConfermaConsegnaDPI.objects.get()
        self.assertEqual((conferma.stato, conferma.nota), ("CONTESTATA", "mancano i guanti"))
        self.assertEqual([m.to for m in mail.outbox if "contestata" in m.subject], [["magazzino@azienda.test"]])
        self.assertEqual(conferme.autoconferma(adesso=timezone.now() + timedelta(days=2)), 0)  # contestata resta tale

    def test_link_dopo_l_autoconferma_non_cambia_nulla(self):
        self._consegna_banco(self._richiesta())
        conferma = ConfermaConsegnaDPI.objects.get()
        base = self._link_vecchio(conferma)
        conferme.autoconferma(adesso=conferma.created_at + timedelta(hours=24))
        self.client.logout()
        self.client.post(base + "contesta/")
        self.assertEqual(ConfermaConsegnaDPI.objects.get().stato, "CONFERMATA")

    def test_link_sbagliato_404(self):
        self.client.logout()
        self.assertEqual(self.client.get("/approval-actions/dpi/inesistente/conferma/").status_code, 404)
        self.assertEqual(self.client.get("/approval-actions/dpi/inesistente/approva/").status_code, 404)
