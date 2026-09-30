"""Flusso DPI: dipendente richiede -> responsabile/preposto approva -> avviso a
magazzino/amministrazione -> report di consegna all'amministrazione."""

from __future__ import annotations

from datetime import date
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from anagrafica.models import (
    AreaAziendale,
    DipendenteAnagraficaAziendale,
    DipendenteRuoloOperativo,
    Reparto,
    RuoloOperativo,
)

from . import flusso
from .models import (
    CategoriaDPI,
    ConsegnaDPI,
    DPIImpostazioni,
    RichiestaDPI,
    StatoRichiesta,
)

User = get_user_model()

DIPENDENTE, CAPO, PREPOSTO, ESTRANEO = 101, 102, 103, 104


class ApprovatoriTests(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="Produzione", caporeparto_legacy_id=CAPO)
        self.area = AreaAziendale.objects.create(nome="Tornitura", reparto=self.reparto)
        for legacy_id in (DIPENDENTE, PREPOSTO):
            DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=legacy_id, area_aziendale=self.area)
        ruolo = RuoloOperativo.objects.create(nome="Preposto")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=PREPOSTO, ruolo=ruolo)

    def test_approvatori_sono_caporeparto_e_preposto(self):
        self.assertEqual(flusso.approvatori_di(DIPENDENTE), {CAPO, PREPOSTO})

    def test_responsabile_area_vince_sul_caporeparto(self):
        self.area.responsabile_legacy_id = 200
        self.area.save()
        self.assertEqual(flusso.approvatori_di(DIPENDENTE), {200, PREPOSTO})
        self.assertNotIn(DIPENDENTE, flusso.dipendenti_di_approvatore(CAPO))

    def test_dipendenti_di_approvatore_e_inverso(self):
        self.assertEqual(flusso.dipendenti_di_approvatore(CAPO), {DIPENDENTE, PREPOSTO})
        self.assertEqual(flusso.dipendenti_di_approvatore(PREPOSTO), {DIPENDENTE})
        self.assertEqual(flusso.dipendenti_di_approvatore(ESTRANEO), set())


@override_settings(
    LEGACY_AUTH_ENABLED=False,
    SECURE_SSL_REDIRECT=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class FlussoViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="dpi-flusso", password="x", email="f@y.z")
        self.client.force_login(self.admin)
        reparto = Reparto.objects.create(nome="Produzione", caporeparto_legacy_id=CAPO)
        area = AreaAziendale.objects.create(nome="Tornitura", reparto=reparto)
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=DIPENDENTE, area_aziendale=area)
        impost = DPIImpostazioni.get_singleton()
        impost.magazzino_emails = "magazzino@example.test"
        impost.amministrazione_emails = "amministrazione@example.test\nsecondo@example.test"
        impost.save()
        self.categoria = CategoriaDPI.objects.create(nome="Guanti", icona_emoji="gloves", vita_utile_giorni=180)
        self.richiesta = RichiestaDPI.objects.create(
            categoria=self.categoria,
            stato=StatoRichiesta.INVIATA,
            richiedente_legacy_id=DIPENDENTE,
            richiedente_nome="Mario Rossi",
            created_by=self.admin,
        )

    def _come_capo(self):
        """Simula un utente non gestore che e' il caporeparto del dipendente."""
        return mock.patch.multiple("dpi.views", _is_gestore=mock.Mock(return_value=False), _legacy_id=mock.Mock(return_value=CAPO))

    def test_capo_approva_e_scatta_l_avviso_a_magazzino_e_amministrazione(self):
        with self._come_capo():
            response = self.client.post(reverse("dpi:approva", args=[self.richiesta.pk]), {"nota": "ok"})
        self.assertEqual(response.status_code, 302)
        self.richiesta.refresh_from_db()
        self.assertEqual(self.richiesta.stato, StatoRichiesta.APPROVATA)
        avviso = [m for m in mail.outbox if "Da consegnare" in m.subject]
        self.assertEqual(len(avviso), 1)
        self.assertIn("magazzino@example.test", avviso[0].to)
        self.assertIn("amministrazione@example.test", avviso[0].to)

    def test_estraneo_non_puo_approvare(self):
        with mock.patch.multiple("dpi.views", _is_gestore=mock.Mock(return_value=False), _legacy_id=mock.Mock(return_value=ESTRANEO)):
            self.client.post(reverse("dpi:approva", args=[self.richiesta.pk]))
        self.richiesta.refresh_from_db()
        self.assertEqual(self.richiesta.stato, StatoRichiesta.INVIATA)

    def test_capo_vede_solo_le_richieste_dei_suoi(self):
        altra = RichiestaDPI.objects.create(
            categoria=self.categoria, stato=StatoRichiesta.INVIATA, richiedente_legacy_id=ESTRANEO, richiedente_nome="Altro Reparto"
        )
        with self._come_capo():
            page = self.client.get(reverse("dpi:gestione_list"))
            self.assertContains(page, "Mario Rossi")
            self.assertNotContains(page, "Altro Reparto")
            self.assertEqual(self.client.get(reverse("dpi:gestione_detail", args=[altra.pk])).status_code, 302)
            detail = self.client.get(reverse("dpi:gestione_detail", args=[self.richiesta.pk]))
            self.assertContains(detail, "Approva richiesta")
            self.assertNotContains(detail, "Registra consegna")

    def test_consegna_solo_dopo_approvazione(self):
        self.client.post(reverse("dpi:consegna", args=[self.richiesta.pk]), {"data_consegna": "2026-09-30"})
        self.assertFalse(ConsegnaDPI.objects.filter(richiesta=self.richiesta).exists())
        self.richiesta.stato = StatoRichiesta.APPROVATA
        self.richiesta.save()
        mail.outbox.clear()
        with mock.patch("dpi.pdf.render_modulo_consegna_dpi", return_value=b"%PDF-1.4 x"):
            self.client.post(reverse("dpi:consegna", args=[self.richiesta.pk]), {"data_consegna": "2026-09-30"})
        consegna = ConsegnaDPI.objects.get(richiesta=self.richiesta)
        self.assertEqual(consegna.data_consegna, date(2026, 9, 30))
        report = [m for m in mail.outbox if "Report di consegna" in m.subject]
        self.assertEqual(len(report), 1)
        self.assertEqual(set(report[0].to), {"amministrazione@example.test", "secondo@example.test"})
        self.assertEqual(report[0].attachments[0][0], f"consegna_dpi_{self.richiesta.numero}.pdf")

    def test_nuova_richiesta_avvisa_il_responsabile(self):
        with mock.patch("dpi.flusso._email_persona", return_value="capo@example.test"):
            flusso.notifica_nuova_richiesta(self.richiesta)
        self.assertEqual([m.to for m in mail.outbox if "da approvare" in m.subject], [["capo@example.test"]])

    def test_capo_richiede_per_un_suo_dipendente(self):
        from core.legacy_models import AnagraficaDipendente  # noqa: F401  (tabella legacy usata dalla view)

        with self._come_capo(), mock.patch("dpi.views._dipendenti_selezionabili", return_value=[{"id": DIPENDENTE, "nome": "Rossi Mario"}]), \
                mock.patch("dpi.flusso.notifica_nuova_richiesta"):
            response = self.client.post(reverse("dpi:nuova"), {
                "richiedente": DIPENDENTE,
                "categoria_id": self.categoria.pk,
                "quantita": "1",
            })
        self.assertEqual(response.status_code, 302)
        nuova = RichiestaDPI.objects.exclude(pk=self.richiesta.pk).get()
        self.assertEqual(nuova.richiedente_legacy_id, DIPENDENTE)
        self.assertEqual(nuova.created_by, self.admin)
        self.assertIn("per conto del dipendente", nuova.note_gestione)

    def test_non_si_richiede_per_chi_non_e_nel_proprio_ambito(self):
        with self._come_capo():
            response = self.client.post(reverse("dpi:nuova"), {
                "richiedente": ESTRANEO,
                "categoria_id": self.categoria.pk,
            })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(RichiestaDPI.objects.exclude(pk=self.richiesta.pk).exists())
