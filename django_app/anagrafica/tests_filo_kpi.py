"""Numeri coerenti e KPI che portano all'azione (qualifiche, conformità, libretto, onboarding).

Dati sintetici.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.legacy_models import AnagraficaDipendente

from .models import DipendenteQualifica, OnboardingPratica, TipoQualifica
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False)
class FiloKpiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("fk_admin", "fk@example.invalid", "x")
        self.client.force_login(self.admin)
        self.oggi = timezone.localdate()
        self.p = AnagraficaDipendente.objects.create(nome="ELIO", cognome="RINNOVATO", aliasusername="fk.elio.t")
        self.tipo = TipoQualifica.objects.create(nome="Carrellista sintetico", categoria=TipoQualifica.CAT_SICUREZZA)
        # Record vecchio scaduto, superato da un rinnovo valido.
        DipendenteQualifica.objects.create(legacy_anagrafica_id=self.p.pk, tipo=self.tipo,
                                           data_conseguimento=self.oggi - timedelta(days=2000),
                                           data_scadenza=self.oggi - timedelta(days=10))
        DipendenteQualifica.objects.create(legacy_anagrafica_id=self.p.pk, tipo=self.tipo,
                                           data_conseguimento=self.oggi - timedelta(days=5),
                                           data_scadenza=self.oggi + timedelta(days=1500))

    def test_scheda_qualifica_non_conta_il_record_rinnovato(self):
        resp = self.client.get(reverse("anagrafica:tipo_qualifica_detail", args=[self.tipo.pk]))
        self.assertEqual(resp.context["n_scaduti"], 0)
        self.assertEqual(resp.context["n_holders"], 1)
        self.assertContains(resp, "#conformita-qualifiche")

    def test_elenco_qualifiche_non_mostra_il_record_rinnovato(self):
        resp = self.client.get(reverse("anagrafica:qualifiche_list"))
        self.assertEqual([s for s in resp.context["scadenze"] if s["legacy_anagrafica_id"] == self.p.pk], [])

    def test_conformita_filtro_mansione_visibile_e_guida(self):
        resp = self.client.get(reverse("anagrafica:conformita_report"), {"mansione": "Saldatore sintetico"})
        self.assertContains(resp, "Saldatore sintetico")
        self.assertContains(resp, "mostra tutti")
        self.assertContains(resp, "#conformita-qualifiche")

    def test_pannello_conformita_vai_alla_sezione(self):
        html = render_to_string("anagrafica/partials/_conformita_dom.html", {
            "dom": {"esito": "ko", "dettagli": ["Corso scaduto"]}, "titolo": "Formazione", "icon": "",
            "vai": "formazione", "vai_ancora": "scheda-formazione"})
        self.assertIn('href="#scheda-formazione"', html)
        self.assertIn('data-tab-vai="formazione"', html)
        html = render_to_string("anagrafica/partials/_conformita_dom.html", {
            "dom": {"esito": "ok", "dettagli": []}, "titolo": "Formazione", "icon": "", "vai": "formazione"})
        self.assertNotIn("Vai alla sezione", html)

    def test_libretto_righe_portano_il_riferimento(self):
        from .services import libretto_sanitario as ls
        corso = SimpleNamespace(pk=77, titolo="Corso sintetico")
        righe = ls._righe_corsi([SimpleNamespace(stato="MAI_FREQUENTATO", corso=corso, origini=[])])
        self.assertEqual(righe[0].ref_id, 77)

    def test_onboarding_riquadri_filtrano(self):
        OnboardingPratica.objects.create(dipendente_nome="Pre Sintetico", stato=OnboardingPratica.STATO_IN_CORSO)
        OnboardingPratica.objects.create(legacy_anagrafica_id=self.p.pk, dipendente_nome="Elio Rinnovato",
                                         data_assunzione=self.oggi + timedelta(days=10),
                                         stato=OnboardingPratica.STATO_IN_CORSO)
        url = reverse("anagrafica:onboarding_list")
        body = self.client.get(url).content.decode()
        self.assertIn("?vista=ingressi", body)
        nomi = [p.dipendente_nome for p in self.client.get(url, {"vista": "pre"}).context["page_obj"]]
        self.assertEqual(nomi, ["Pre Sintetico"])
        nomi = [p.dipendente_nome for p in self.client.get(url, {"vista": "ingressi"}).context["page_obj"]]
        self.assertEqual(nomi, ["Elio Rinnovato"])

    def test_matrice_qualifiche_nome_e_cella_corrente(self):
        resp = self.client.get(reverse("anagrafica:matrice_competenze"))
        self.assertContains(resp, "Matrice qualifiche")

    def test_mpq_kpi_portano_alle_scadenze(self):
        resp = self.client.get(reverse("anagrafica:mpq_cruscotto"))
        self.assertContains(resp, 'id="scadenze-urgenti"')
        self.assertContains(resp, 'href="#scadenze-urgenti"')
