"""Regola unica capo/team (fase 2a, 16/10/2026) e pagina «Coerenza capi».

Esempio: Responsabile produzione ← Caporeparto ← Operatore.
Fresatura (aree IN1, IN2), Saldatura (area SA1).
"""
from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import AreaAziendale, DipendenteAnagraficaAziendale, DipendenteRuoloOperativo, Reparto, RuoloOperativo
from .services import capo_team
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class _Scenario(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
        self.fresatura = Reparto.objects.create(nome="Fresatura")
        self.saldatura = Reparto.objects.create(nome="Saldatura")
        self.in1 = AreaAziendale.objects.create(nome="IN1", reparto=self.fresatura)
        self.in2 = AreaAziendale.objects.create(nome="IN2", reparto=self.fresatura)
        self.sa1 = AreaAziendale.objects.create(nome="SA1", reparto=self.saldatura)
        self.resp = RuoloOperativo.objects.create(nome="Responsabile produzione")
        self.capo = RuoloOperativo.objects.create(nome="Caporeparto", riporta_a=self.resp)
        self.op = RuoloOperativo.objects.create(nome="Operatore", riporta_a=self.capo)
        self.gialli = self._persona("gialli", "Direzione", None, self.resp)
        self.bianchi = self._persona("bianchi", "Fresatura", self.in2, self.capo)
        self.neri = self._persona("neri", "Saldatura", self.sa1, self.capo)
        self.rossi = self._persona("rossi", "Fresatura", self.in1, self.op)
        self.verdi = self._persona("verdi", "Saldatura", self.sa1, self.op)

    def _persona(self, alias, reparto, area, ruolo):
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, reparto, mansione, attivo) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [alias, alias.capitalize(), alias.upper(), reparto, "", 1],
            )
            cursor.execute("SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", [alias])
            legacy_id = int(cursor.fetchone()[0])
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=legacy_id, area=reparto, area_aziendale=area)
        if ruolo is not None:
            DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=legacy_id, ruolo=ruolo)
        return legacy_id

    def _capo(self, legacy_id):
        return capo_team.capo_di(legacy_id)



@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CapoTeamTests(_Scenario):
    # ── Organigramma: ruolo sopra + stesso perimetro ──────────────────────
    def test_organigramma_stesso_reparto(self):
        capo = self._capo(self.rossi)
        self.assertEqual(capo.legacy_id, self.bianchi)
        self.assertEqual(capo.origine, capo_team.ORIGINE_ORGANIGRAMMA)

    def test_stesso_ruolo_altro_reparto_non_e_il_capo(self):
        self.assertEqual(self._capo(self.verdi).legacy_id, self.neri)

    def test_in_cima_vale_la_persona_unica_del_livello_sopra(self):
        self.assertEqual(self._capo(self.bianchi).legacy_id, self.gialli)

    def test_senza_caporeparto_si_sale_di_livello(self):
        DipendenteRuoloOperativo.objects.filter(legacy_anagrafica_id=self.bianchi).delete()
        self.assertEqual(self._capo(self.rossi).legacy_id, self.gialli)

    def test_area_vince_sul_reparto_fra_candidati(self):
        altro = self._persona("azzurri", "Fresatura", self.in1, self.capo)
        capo = self._capo(self.rossi)
        self.assertEqual(capo.legacy_id, altro)
        self.assertEqual(capo.alternative, [])

    def test_piu_candidati_segnalati(self):
        altro = self._persona("azzurri", "Fresatura", self.in2, self.capo)
        capo = self._capo(self.rossi)
        self.assertEqual(capo.legacy_id, min(altro, self.bianchi))
        self.assertEqual(capo.alternative, [max(altro, self.bianchi)])

    def test_ruolo_concluso_non_conta(self):
        DipendenteRuoloOperativo.objects.filter(legacy_anagrafica_id=self.bianchi).update(
            data_inizio="2020-01-01", data_fine="2020-12-31"
        )
        self.assertEqual(self._capo(self.rossi).legacy_id, self.gialli)

    # ── Eccezioni manuali ─────────────────────────────────────────────────
    def test_caporeparto_indicato_a_mano_vince_sull_organigramma(self):
        self.fresatura.caporeparto_legacy_id = self.neri
        self.fresatura.save()
        capo = self._capo(self.rossi)
        self.assertEqual((capo.legacy_id, capo.origine), (self.neri, capo_team.ORIGINE_REPARTO))

    def test_responsabile_area_vince_sul_reparto(self):
        self.fresatura.caporeparto_legacy_id = self.neri
        self.fresatura.save()
        self.in1.responsabile_legacy_id = self.gialli
        self.in1.save()
        capo = self._capo(self.rossi)
        self.assertEqual((capo.legacy_id, capo.origine), (self.gialli, capo_team.ORIGINE_AREA))

    def test_eccezione_persona_vince_su_tutto(self):
        self.in1.responsabile_legacy_id = self.gialli
        self.in1.save()
        DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=self.rossi).update(
            capo_eccezione_legacy_id=self.neri
        )
        capo = self._capo(self.rossi)
        self.assertEqual((capo.legacy_id, capo.origine), (self.neri, capo_team.ORIGINE_PERSONA))

    def test_il_caporeparto_non_e_capo_di_se_stesso(self):
        self.fresatura.caporeparto_legacy_id = self.bianchi
        self.fresatura.save()
        self.assertEqual(self._capo(self.bianchi).legacy_id, self.gialli)

    # ── Team ──────────────────────────────────────────────────────────────
    def test_team_a_cascata(self):
        mappa = capo_team.mappa_capi()
        self.assertEqual(capo_team.team_di(self.bianchi, mappa=mappa), {self.rossi})
        self.assertEqual(
            capo_team.team_di(self.gialli, mappa=mappa), {self.bianchi, self.neri, self.rossi, self.verdi}
        )
        self.assertEqual(capo_team.team_di(self.gialli, mappa=mappa, solo_diretti=True), {self.bianchi, self.neri})

    # ── Pagina «Coerenza capi» ────────────────────────────────────────────
    def test_pagina_e_eccezione(self):
        admin = User.objects.create_superuser(username="cc_admin", email="cc@x.local", password="x")
        self.client.force_login(admin)
        resp = self.client.get(reverse("anagrafica:coerenza_capi"), {"filtro": "cambia"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Coerenza capi")

        url = reverse("anagrafica:coerenza_capi_eccezione", args=[self.rossi])
        self.client.post(url, {"capo": str(self.neri), "motivo": ""})
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.rossi)
        self.assertIsNone(az.capo_eccezione_legacy_id)  # senza motivo non si salva

        self.client.post(url, {"capo": str(self.neri), "motivo": "distacco"})
        az.refresh_from_db()
        self.assertEqual((az.capo_eccezione_legacy_id, az.capo_eccezione_motivo), (self.neri, "distacco"))

        self.client.post(url, {"capo": "", "motivo": ""})
        az.refresh_from_db()
        self.assertIsNone(az.capo_eccezione_legacy_id)

    def test_eccezione_su_se_stessi_rifiutata(self):
        admin = User.objects.create_superuser(username="cc_admin2", email="cc2@x.local", password="x")
        self.client.force_login(admin)
        self.client.post(
            reverse("anagrafica:coerenza_capi_eccezione", args=[self.rossi]),
            {"capo": str(self.rossi), "motivo": "x"},
        )
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.rossi)
        self.assertIsNone(az.capo_eccezione_legacy_id)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RegolaUnicaPassaggioTests(_Scenario):
    """Fase 2b: con l'interruttore acceso i moduli usano la regola unica."""

    def setUp(self):
        super().setUp()
        from django.core.cache import cache

        cache.clear()
        # Regola di prima per Rossi: il caporeparto indicato a mano è Neri.
        self.fresatura.caporeparto_legacy_id = self.neri
        self.fresatura.save()
        DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=self.rossi).update(
            capo_eccezione_legacy_id=self.bianchi, capo_eccezione_motivo="prova"
        )

    def test_spenta_i_moduli_restano_sulla_regola_di_prima(self):
        from dpi.flusso import approvatori_di

        self.assertFalse(capo_team.regola_unica_attiva())
        self.assertIn(self.neri, approvatori_di(self.rossi))
        self.assertNotIn(self.bianchi, approvatori_di(self.rossi))

    def test_accesa_dpi_assenze_e_mappa_usano_la_regola_unica(self):
        from assenze.views import _capo_regola_unica
        from dpi.flusso import approvatori_di, dipendenti_di_approvatore
        from anagrafica.services.reparto_canonico import build_responsabile_effettivo_map

        capo_team.imposta_regola_unica(True)
        self.assertEqual(capo_team.capo_effettivo(self.rossi), self.bianchi)
        self.assertIn(self.bianchi, approvatori_di(self.rossi))
        self.assertNotIn(self.neri, approvatori_di(self.rossi))
        self.assertIn(self.rossi, dipendenti_di_approvatore(self.bianchi))
        self.assertEqual(_capo_regola_unica(self.rossi), self.bianchi)
        self.assertEqual(build_responsabile_effettivo_map([self.rossi]), {self.rossi: self.bianchi})

    def test_accesa_team_dei_permessi(self):
        from core.permessi import team

        capo_team.imposta_regola_unica(True)
        with mock.patch.object(team, "_anagrafica_ids_di", return_value=[self.gialli]):
            # Gialli: Bianchi e Neri diretti; Rossi (eccezione → Bianchi) e Verdi (→ Neri) a cascata.
            self.assertEqual(team._team_regola_unica(999), {self.bianchi, self.neri, self.rossi, self.verdi})

    def test_interruttore_dalla_pagina_con_conferma_e_schede_riallineate(self):
        admin = User.objects.create_superuser(username="cc_switch", email="sw@x.local", password="x")
        self.client.force_login(admin)
        url = reverse("anagrafica:coerenza_capi")
        self.client.post(url, {"azione": "regola", "attiva": "1"})
        self.assertFalse(capo_team.regola_unica_attiva())  # senza conferma no
        self.client.post(url, {"azione": "regola", "attiva": "1", "conferma": "1"})
        self.assertTrue(capo_team.regola_unica_attiva())
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.rossi)
        self.assertEqual(az.caporeparto_legacy_id, self.bianchi)
        self.client.post(url, {"azione": "regola", "attiva": "0"})
        self.assertFalse(capo_team.regola_unica_attiva())
        az.refresh_from_db()
        self.assertEqual(az.caporeparto_legacy_id, self.neri)

    def test_accesa_una_modifica_riallinea_le_schede_dopo_il_commit(self):
        capo_team.imposta_regola_unica(True)
        capo_team.riallinea_tutte_le_schede()
        with self.captureOnCommitCallbacks(execute=True):
            az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.rossi)
            az.capo_eccezione_legacy_id = self.gialli
            az.save()
        az.refresh_from_db()
        self.assertEqual(az.caporeparto_legacy_id, self.gialli)
