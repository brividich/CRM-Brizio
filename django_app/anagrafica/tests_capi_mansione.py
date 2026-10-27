"""Capo del reparto deciso dalla mansione (26/10/2026) e pagina «Reparti, aree e capi».

Stesso scenario di ``tests_capo_team``: Responsabile produzione ← Caporeparto ←
Operatore; Fresatura (IN1, IN2), Saldatura (SA1).
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.urls import reverse

from core.models import RepartoCapoMapping

from .models import DipendenteAnagraficaAziendale, Reparto
from .models_skillmatrix import AbilitazioneMacchina, CompetenzaSkm
from .services import capi_mansione, capo_team
from .tests_capo_team import _Scenario

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class _ScenarioMansioni(_Scenario):
    def setUp(self):
        super().setUp()
        cache.clear()
        # Come in produzione: il ruolo responsabile del reparto genera la sua
        # «Responsabilità del reparto» (segnali_struttura); senza, si spegne.
        for rep in (self.fresatura, self.saldatura):
            rep.ruolo_responsabile = self.capo
            rep.save()
        self.resp_fres = CompetenzaSkm.objects.get(responsabilita_reparto=self.fresatura)
        self.resp_sald = CompetenzaSkm.objects.get(responsabilita_reparto=self.saldatura)

    def _mansione(self, nome, reparto=None):
        return CompetenzaSkm.objects.create(
            competenza_key=nome.lower().replace(" ", "_"), display=nome,
            tipo=CompetenzaSkm.TIPO_PROCESSO, responsabilita_reparto=reparto,
        )

    def _assegna(self, mansione, legacy_id):
        return AbilitazioneMacchina.objects.create(legacy_anagrafica_id=legacy_id, competenza=mansione, livello="U")

    def _accendi(self):
        capo_team.imposta_regola_unica(True)


class CapoDaMansioneTests(_ScenarioMansioni):
    def test_capo_e_chi_ha_la_responsabilita_del_reparto(self):
        self._assegna(self.resp_fres, self.neri)  # Neri sta in Saldatura ma guida Fresatura
        self._accendi()
        capo = capo_team.capo_di(self.rossi)
        self.assertEqual((capo.legacy_id, capo.origine), (self.neri, capo_team.ORIGINE_REPARTO))

    def test_spenta_vale_ancora_il_capo_scelto_a_mano(self):
        self._assegna(self.resp_fres, self.neri)
        self.fresatura.caporeparto_legacy_id = self.gialli
        self.fresatura.save()
        self.assertEqual(capo_team.capo_di(self.rossi).legacy_id, self.gialli)

    def test_mansione_del_capo_scelta_per_il_reparto(self):
        """Caso UT: il capo ha un'altra mansione, non la «Responsabilità del reparto»."""
        direttore_tecnico = self._mansione("Direttore tecnico")
        self.fresatura.mansione_capo = direttore_tecnico
        self.fresatura.save()
        self._assegna(self.resp_fres, self.neri)
        self._assegna(direttore_tecnico, self.gialli)
        self._accendi()
        self.assertEqual(capo_team.capo_di(self.rossi).legacy_id, self.gialli)

    def test_area_con_mansione_propria_vince_sul_reparto(self):
        hse = self._mansione("Responsabile HSE")
        self.in1.mansione_capo = hse
        self.in1.save()
        self._assegna(self.resp_fres, self.neri)
        self._assegna(hse, self.gialli)
        self._accendi()
        capo = capo_team.capo_di(self.rossi)  # Rossi è in IN1
        self.assertEqual((capo.legacy_id, capo.origine), (self.gialli, capo_team.ORIGINE_AREA))

    def test_area_senza_titolari_segue_il_reparto(self):
        self.in1.mansione_capo = self._mansione("Responsabile HSE")
        self.in1.save()
        self._assegna(self.resp_fres, self.neri)
        self._accendi()
        self.assertEqual(capo_team.capo_di(self.rossi).legacy_id, self.neri)

    def test_chi_ha_la_mansione_non_e_capo_di_se_stesso(self):
        self._assegna(self.resp_fres, self.bianchi)
        self._accendi()
        self.assertEqual(capo_team.capo_di(self.rossi).legacy_id, self.bianchi)
        self.assertEqual(capo_team.capo_di(self.bianchi).legacy_id, self.gialli)  # organigramma

    def test_piu_titolari_sono_co_capi(self):
        self._assegna(self.resp_fres, self.neri)
        self._assegna(self.resp_fres, self.gialli)
        self._accendi()
        capo = capo_team.capo_di(self.rossi)
        self.assertEqual(capo.legacy_id, min(self.neri, self.gialli))
        self.assertEqual(capo.alternative, [max(self.neri, self.gialli)])
        self.assertEqual(capo_team.co_capi_in_cache()[self.rossi], [max(self.neri, self.gialli)])

    def test_dpi_approvano_capo_e_co_capi(self):
        from dpi.flusso import approvatori_di, dipendenti_di_approvatore

        self._assegna(self.resp_fres, self.neri)
        self._assegna(self.resp_fres, self.gialli)
        self._accendi()
        self.assertTrue({self.neri, self.gialli} <= approvatori_di(self.rossi))
        self.assertIn(self.rossi, dipendenti_di_approvatore(max(self.neri, self.gialli)))

    def test_mansione_tolta_o_sospesa_non_conta(self):
        ab = self._assegna(self.resp_fres, self.neri)
        self._accendi()
        ab.in_lista = False
        ab.save()
        cache.clear()
        self.assertEqual(capo_team.capo_di(self.rossi).legacy_id, self.bianchi)  # organigramma


class CopieDerivateTests(_ScenarioMansioni):
    def test_assegnare_la_mansione_riallinea_reparto_schede_e_mapping(self):
        with connection.cursor() as cursor:
            cursor.execute("UPDATE anagrafica_dipendenti SET email = %s WHERE id = %s", ["neri@example.local", self.neri])
        self._accendi()
        with self.captureOnCommitCallbacks(execute=True):
            self._assegna(self.resp_fres, self.neri)
        self.fresatura.refresh_from_db()
        self.assertEqual(self.fresatura.caporeparto_legacy_id, self.neri)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.rossi)
        self.assertEqual(az.caporeparto_legacy_id, self.neri)
        self.assertTrue(RepartoCapoMapping.objects.filter(reparto="Fresatura").exists())

    def test_mapping_usa_l_account_della_persona_non_l_id_di_anagrafica(self):
        from core.legacy_models import UtenteLegacy

        utente = UtenteLegacy.objects.create(nome="Neri Account", email="neri@example.local", ruolo="")
        with connection.cursor() as cursor:
            cursor.execute("UPDATE anagrafica_dipendenti SET utente_id = %s WHERE id = %s", [utente.pk, self.neri])
        self.assertEqual(capi_mansione.valore_mapping(self.neri), "neri@example.local")

    def test_righe_di_mapping_di_reparti_inesistenti_spariscono(self):
        RepartoCapoMapping.objects.create(reparto="REPARTO CHE NON C'E", caporeparto="x@example.local")
        self._accendi()
        capi_mansione.allinea_derivati()
        self.assertFalse(RepartoCapoMapping.objects.filter(reparto="REPARTO CHE NON C'E").exists())


class PassaggioTests(_ScenarioMansioni):
    def setUp(self):
        super().setUp()
        self.fresatura.caporeparto_legacy_id = self.bianchi
        self.fresatura.save()
        self.saldatura.caporeparto_legacy_id = self.neri
        self.saldatura.save()

    def test_proposta_assegna_la_mansione_a_chi_oggi_e_capo(self):
        p = capi_mansione.proposta()
        self.assertFalse(p.bloccata)
        self.assertEqual({(a["mansione"].pk, a["legacy_id"]) for a in p.assegnazioni},
                         {(self.resp_fres.pk, self.bianchi), (self.resp_sald.pk, self.neri)})

    def test_passaggio_nessuno_cambia_capo(self):
        prima = {pid: c.legacy_id for pid, c in capo_team.mappa_capi().items()}
        capi_mansione.applica_passaggio()
        cache.clear()
        self.assertTrue(capo_team.regola_unica_attiva())
        dopo = {pid: c.legacy_id for pid, c in capo_team.mappa_capi().items()}
        self.assertEqual(prima, dopo)
        self.assertTrue(AbilitazioneMacchina.objects.filter(competenza=self.resp_fres,
                                                            legacy_anagrafica_id=self.bianchi).exists())

    def test_reparto_senza_mansione_blocca_il_passaggio(self):
        Reparto.objects.create(nome="UT")
        self.assertTrue(capi_mansione.proposta().bloccata)
        with self.assertRaises(ValueError):
            capi_mansione.applica_passaggio()
        self.assertFalse(capo_team.regola_unica_attiva())

    def test_area_con_responsabile_diverso_da_decidere(self):
        self.in1.responsabile_legacy_id = self.gialli
        self.in1.save()
        self.assertEqual([a.pk for a in capi_mansione.proposta().aree_da_decidere], [self.in1.pk])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class PaginaRepartiCapiTests(_ScenarioMansioni):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(username="rc_admin", email="rc@x.local", password="x")
        self.client.force_login(self.admin)

    def test_pagina_mostra_reparti_mansione_e_passaggio(self):
        resp = self.client.get(reverse("anagrafica:aree_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Reparti, aree e capi")
        self.assertContains(resp, "Responsabilità del reparto Fresatura")
        self.assertContains(resp, "Passaggio ai capi decisi dalla mansione")

    def test_passaggio_dalla_pagina_serve_la_conferma(self):
        url = reverse("anagrafica:capi_passaggio")
        self.client.post(url, {})
        self.assertFalse(capo_team.regola_unica_attiva())
        self.client.post(url, {"conferma": "1"})
        self.assertTrue(capo_team.regola_unica_attiva())
        resp = self.client.get(reverse("anagrafica:aree_list"))
        self.assertNotContains(resp, "Passaggio ai capi decisi dalla mansione")

    def test_assegna_e_togli_dalla_pagina(self):
        self._accendi()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("anagrafica:capo_assegna", args=[self.resp_fres.pk]),
                             {"legacy_id": str(self.neri), "ancora": "rep-1"})
        self.fresatura.refresh_from_db()
        self.assertEqual(self.fresatura.caporeparto_legacy_id, self.neri)
        ab = AbilitazioneMacchina.objects.get(competenza=self.resp_fres, legacy_anagrafica_id=self.neri)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("anagrafica:capo_togli", args=[ab.pk]))
        self.fresatura.refresh_from_db()
        self.assertIsNone(self.fresatura.caporeparto_legacy_id)

    def test_assegna_solo_su_mansioni_del_capo(self):
        altra = self._mansione("Fresatura CNC")
        self.client.post(reverse("anagrafica:capo_assegna", args=[altra.pk]), {"legacy_id": str(self.neri)})
        self.assertFalse(AbilitazioneMacchina.objects.filter(competenza=altra).exists())

    def test_non_admin_non_cambia(self):
        utente = User.objects.create_user(username="rc_user", password="x")
        self.client.force_login(utente)
        self.client.post(reverse("anagrafica:capi_passaggio"), {"conferma": "1"})
        self.assertFalse(capo_team.regola_unica_attiva())
