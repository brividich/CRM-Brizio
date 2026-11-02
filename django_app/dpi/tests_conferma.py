"""Conferma di ricevuta via mail al posto della firma: al dipendente con mail
aziendale, altrimenti al caporeparto; link pubblico monouso; contestazione; sollecito."""

from __future__ import annotations

import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import conferme
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
_RE_LINK = re.compile(r"/approval-actions/dpi/([^/\s]+)/(conferma|contesta)/")


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
        impost.domini_email_aziendali = "azienda.test"
        impost.magazzino_emails = "magazzino@azienda.test"
        impost.save()
        for target in ("dpi.pdf.render_modulo_consegna_dpi",):
            p = mock.patch(target, return_value=b"%PDF")
            p.start()
            self.addCleanup(p.stop)
        self.email_persona = {101: "mario.rossi@azienda.test", 102: "luigi@gmail.test"}
        p = mock.patch("dpi.flusso._email_persona", side_effect=lambda lid: self.email_persona.get(int(lid), ""))
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch("dpi.flusso.email_preposti", return_value=["capo@azienda.test"])
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
        return [m for m in mail.outbox if "Conferma la ricevuta" in m.subject or "conferma la ricevuta" in m.subject]

    def _link(self, decisione="conferma"):
        m = self._mail_conferma()[-1]
        token = _RE_LINK.search(m.body).group(1)
        return f"/approval-actions/dpi/{token}/{decisione}/"

    def test_senza_firma_una_mail_al_dipendente_con_mail_aziendale(self):
        a, b = self._richiesta(), self._richiesta()
        self._consegna_banco(a, b)
        conferma = ConfermaConsegnaDPI.objects.get()
        self.assertEqual(conferma.destinatario_tipo, "DIPENDENTE")
        self.assertEqual(conferma.consegne.count(), 2)
        inviate = self._mail_conferma()
        self.assertEqual(len(inviate), 1)
        self.assertEqual(inviate[0].to, ["mario.rossi@azienda.test"])
        a.refresh_from_db()
        self.assertEqual(a.stato, StatoRichiesta.CONSEGNATA)  # la consegna vale subito

    def test_mail_non_aziendale_va_al_caporeparto(self):
        r = self._richiesta(legacy=102, nome="Luigi Verdi")
        self._consegna_banco(r)
        self.assertEqual(ConfermaConsegnaDPI.objects.get().destinatario_tipo, "RESPONSABILE")
        self.assertEqual(self._mail_conferma()[0].to, ["capo@azienda.test"])

    def test_con_firma_o_carta_nessuna_conferma(self):
        self._consegna_banco(self._richiesta(), firmato_ricevuta="1")
        self.assertFalse(ConfermaConsegnaDPI.objects.exists())
        self.assertEqual(self._mail_conferma(), [])

    def test_consegna_dalla_scheda_chiede_conferma(self):
        r = self._richiesta()
        self.client.post(reverse("dpi:consegna", args=[r.pk]), {"data_consegna": "2026-11-02"})
        self.assertEqual(ConfermaConsegnaDPI.objects.get().consegne.get().richiesta_id, r.pk)

    def test_link_pubblico_get_non_decide_post_conferma_una_volta(self):
        self._consegna_banco(self._richiesta())
        url = self._link()
        self.client.logout()
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Hai ricevuto questi DPI?")
        self.assertEqual(ConfermaConsegnaDPI.objects.get().stato, "IN_ATTESA")
        self.assertEqual(self.client.post(url).status_code, 302)
        conferma = ConfermaConsegnaDPI.objects.get()
        self.assertEqual((conferma.stato, conferma.decisa_da_email), ("CONFERMATA", "mario.rossi@azienda.test"))
        # Secondo click (anche «contesta»): resta confermata.
        self.client.post(url.replace("/conferma/", "/contesta/"))
        self.assertEqual(ConfermaConsegnaDPI.objects.get().stato, "CONFERMATA")
        self.assertContains(self.client.get(url), "Ricevuta confermata")

    def test_contestazione_avvisa_il_magazzino(self):
        self._consegna_banco(self._richiesta())
        url = self._link("contesta")
        self.client.logout()
        mail.outbox.clear()
        self.client.post(url, {"nota": "mancano i guanti"})
        conferma = ConfermaConsegnaDPI.objects.get()
        self.assertEqual((conferma.stato, conferma.nota), ("CONTESTATA", "mancano i guanti"))
        avvisi = [m for m in mail.outbox if "contestata" in m.subject]
        self.assertEqual(avvisi[0].to, ["magazzino@azienda.test"])
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("dpi:banco")), "mancano i guanti")

    def test_link_sbagliato_404(self):
        self.client.logout()
        self.assertEqual(self.client.get("/approval-actions/dpi/inesistente/conferma/").status_code, 404)
        self.assertEqual(self.client.get("/approval-actions/dpi/inesistente/approva/").status_code, 404)

    def test_sollecito_una_volta_con_link_nuovo(self):
        self._consegna_banco(self._richiesta())
        vecchio = self._link()
        ConfermaConsegnaDPI.objects.update(created_at=timezone.now() - timedelta(days=4))
        mail.outbox.clear()
        self.assertEqual(conferme.sollecita(), 1)
        self.assertEqual(conferme.sollecita(), 0)  # un solo sollecito
        self.assertIn("Promemoria", self._mail_conferma()[0].subject)
        self.client.logout()
        self.assertEqual(self.client.get(vecchio).status_code, 404)  # il vecchio link non vale piu'
        self.assertEqual(self.client.get(self._link()).status_code, 200)
        self.assertEqual(LinkConfermaDPI.objects.count(), 1)
