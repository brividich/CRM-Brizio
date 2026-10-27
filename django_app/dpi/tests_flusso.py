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

    def test_capo_approva_e_scatta_l_avviso_al_solo_magazzino(self):
        with self._come_capo():
            response = self.client.post(reverse("dpi:approva", args=[self.richiesta.pk]), {"nota": "ok"})
        self.assertEqual(response.status_code, 302)
        self.richiesta.refresh_from_db()
        self.assertEqual(self.richiesta.stato, StatoRichiesta.APPROVATA)
        self.assertIsNone(self.richiesta.pronta_ritiro_il)
        avviso = [m for m in mail.outbox if "Da consegnare" in m.subject]
        self.assertEqual(len(avviso), 1)
        self.assertEqual(avviso[0].to, ["magazzino@example.test"])
        self.assertFalse([m for m in mail.outbox if "pronto" in m.subject])

    def test_magazzino_segna_pronto_e_il_dipendente_e_avvisato(self):
        self.richiesta.stato = StatoRichiesta.APPROVATA
        self.richiesta.save()
        with mock.patch("dpi.flusso._email_persona", return_value="mario@example.test"):
            self.client.post(reverse("dpi:pronta_ritiro", args=[self.richiesta.pk]))
        self.richiesta.refresh_from_db()
        self.assertIsNotNone(self.richiesta.pronta_ritiro_il)
        self.assertEqual(self.richiesta.label_stato, "Pronta al ritiro")
        ritiro = [m for m in mail.outbox if "pronto" in m.subject]
        self.assertEqual([m.to for m in ritiro], [["mario@example.test"]])

    def test_pagine_del_gestore_mostrano_ritiro_e_spunte(self):
        self.richiesta.stato = StatoRichiesta.APPROVATA
        self.richiesta.save()
        detail = self.client.get(reverse("dpi:gestione_detail", args=[self.richiesta.pk]))
        self.assertContains(detail, "Pronto per il ritiro")
        self.assertContains(detail, "Registra consegna")
        impost = self.client.get(reverse("dpi:impostazioni"))
        self.assertContains(impost, 'name="avviso_ritiro_all_approvazione"')
        nuova_cat = self.client.get(reverse("dpi:categoria_modifica", args=[self.categoria.pk]))
        self.assertContains(nuova_cat, 'name="avvisa_amministrazione_consegna"')

    def test_pronto_solo_per_i_gestori(self):
        self.richiesta.stato = StatoRichiesta.APPROVATA
        self.richiesta.save()
        with self._come_capo():
            self.client.post(reverse("dpi:pronta_ritiro", args=[self.richiesta.pk]))
        self.richiesta.refresh_from_db()
        self.assertIsNone(self.richiesta.pronta_ritiro_il)

    def test_opzione_avviso_ritiro_subito_all_approvazione(self):
        impost = DPIImpostazioni.get_singleton()
        impost.avviso_ritiro_all_approvazione = True
        impost.save()
        with self._come_capo(), mock.patch("dpi.flusso._email_persona", return_value="mario@example.test"):
            self.client.post(reverse("dpi:approva", args=[self.richiesta.pk]))
        self.richiesta.refresh_from_db()
        self.assertTrue(self.richiesta.is_pronta_ritiro)
        self.assertEqual(len([m for m in mail.outbox if "pronto" in m.subject]), 1)

    def test_report_consegna_al_preposto_e_amministrazione_solo_se_la_categoria_lo_chiede(self):
        self.richiesta.stato = StatoRichiesta.APPROVATA
        self.richiesta.save()
        self.categoria.avvisa_amministrazione_consegna = False
        self.categoria.save()
        with mock.patch("dpi.pdf.render_modulo_consegna_dpi", return_value=b"%PDF-1.4 x"), \
                mock.patch("dpi.flusso._email_persona", side_effect=lambda i: f"p{i}@example.test"):
            self.client.post(reverse("dpi:consegna", args=[self.richiesta.pk]), {"data_consegna": "2026-09-30"})
        report = [m for m in mail.outbox if "Report di consegna" in m.subject]
        self.assertEqual(report[0].to, [f"p{CAPO}@example.test"])

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
            self.assertContains(page, "MARIO ROSSI")
            self.assertNotContains(page, "ALTRO REPARTO")
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

    def test_spunta_referenti_aggiunge_i_referenti_alla_nuova_richiesta(self):
        impost = DPIImpostazioni.get_singleton()
        impost.notifica_nuova_richiesta = True
        impost.responsabili = [{"nome": "Rspp", "email": "rspp@example.test"}]
        impost.notifica_email_extra = "hse@example.test"
        impost.save()
        with mock.patch("dpi.flusso._email_persona", return_value="capo@example.test"):
            flusso.notifica_nuova_richiesta(self.richiesta)
        avviso = [m for m in mail.outbox if "da approvare" in m.subject]
        self.assertEqual(set(avviso[0].to), {"capo@example.test", "rspp@example.test", "hse@example.test"})

    def test_rifiuto_dopo_approvazione_annulla_la_consegna(self):
        self.richiesta.stato = StatoRichiesta.APPROVATA
        self.richiesta.save()
        with self._come_capo():
            self.client.post(reverse("dpi:rifiuta", args=[self.richiesta.pk]), {"motivazione": "doppione"})
        annullo = [m for m in mail.outbox if "Consegna annullata" in m.subject]
        self.assertEqual(len(annullo), 1)
        self.assertIn("magazzino@example.test", annullo[0].to)
        self.assertIn("doppione", annullo[0].body)

    def test_rifiuto_di_richiesta_non_approvata_non_scrive_al_magazzino(self):
        with self._come_capo():
            self.client.post(reverse("dpi:rifiuta", args=[self.richiesta.pk]), {"motivazione": "no"})
        self.assertFalse([m for m in mail.outbox if "Consegna annullata" in m.subject])

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
        # Inserita dal CAR: approvata da sola, il magazzino e' avvisato.
        self.assertEqual(nuova.stato, StatoRichiesta.APPROVATA)
        self.assertEqual(len([m for m in mail.outbox if "Da consegnare" in m.subject]), 1)

    def test_richiesta_di_un_operatore_resta_da_approvare(self):
        with mock.patch.multiple("dpi.views", _is_gestore=mock.Mock(return_value=False), _legacy_id=mock.Mock(return_value=DIPENDENTE)), \
                mock.patch("dpi.flusso.notifica_nuova_richiesta") as da_approvare:
            self.client.post(reverse("dpi:nuova"), {"categoria_id": self.categoria.pk, "quantita": "1"})
        nuova = RichiestaDPI.objects.exclude(pk=self.richiesta.pk).get()
        self.assertEqual(nuova.stato, StatoRichiesta.INVIATA)
        self.assertTrue(da_approvare.called)

    def test_non_si_richiede_per_chi_non_e_nel_proprio_ambito(self):
        with self._come_capo():
            response = self.client.post(reverse("dpi:nuova"), {
                "richiedente": ESTRANEO,
                "categoria_id": self.categoria.pk,
            })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(RichiestaDPI.objects.exclude(pk=self.richiesta.pk).exists())
