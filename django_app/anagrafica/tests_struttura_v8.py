"""Struttura della Qualità (MEGA SKILL MATRIX v8): caricamento, ruoli, aree, revisioni, rischi.

Dati sintetici che riproducono la forma del portale di oggi (reparti, aree, ruoli
del gestionale), mai dati reali.
"""
from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from assets.models import Asset
from core.legacy_models import AnagraficaDipendente

from .models import (
    AmbitoRuolo, AreaAziendale, CompetenzaSkm, DipendenteAnagraficaAziendale, DipendenteRuoloOperativo, Mansione,
    Reparto, RuoloOperativo, RuoloQualifica, StrutturaRevisione, TipoQualifica,
)
from .services import struttura_revisioni as rev
from .services import struttura_rischi as rischi
from .services import struttura_ruoli, struttura_v8
from .tests import _ensure_anagrafica_table

User = get_user_model()


def _assegna(persona, ruolo, principale=True):
    DipendenteRuoloOperativo.objects.create(
        legacy_anagrafica_id=persona.pk, ruolo=ruolo,
        tipologia=DipendenteRuoloOperativo.TIPOLOGIA_PRINCIPALE if principale else "",
    )
    if principale:
        DipendenteAnagraficaAziendale.objects.update_or_create(
            legacy_anagrafica_id=persona.pk, defaults={"ruolo_aziendale": ruolo.nome})


@override_settings(LEGACY_AUTH_ENABLED=False)
class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        from core.models import AccessGroup

        self.user = User.objects.create_superuser("v8_admin", "v8@example.invalid", "x")
        AmbitoRuolo.objects.get_or_create(nome="Produttivo", defaults={"alimenta_scheda": True})
        self.produttivo = AmbitoRuolo.objects.get(nome="Produttivo")
        self.produttivo.alimenta_scheda = True
        self.produttivo.save()
        # Reparti e aree come oggi
        self.alesatrici = Reparto.objects.create(nome="CNC5 - ALESATRICI")
        self.a_alesatrici = AreaAziendale.objects.create(nome="Alesatrici", reparto=self.alesatrici)
        self.a_cn5g = AreaAziendale.objects.create(nome="CN5G", reparto=self.alesatrici)
        self.ut = Reparto.objects.create(nome="UT")
        self.a_in1 = AreaAziendale.objects.create(nome="IN1", reparto=self.ut)
        self.a_vendite = AreaAziendale.objects.create(nome="Vendite", reparto=self.ut)
        self.logistica = Reparto.objects.create(nome="LOGISTICA")
        self.a_manut = AreaAziendale.objects.create(nome="Manutenzione", reparto=self.logistica)
        # Ruoli del gestionale
        self.r_cnc = RuoloOperativo.objects.create(nome="Operatore CNC", ambito=self.produttivo)
        self.r_cn5 = RuoloOperativo.objects.create(nome="Operatore CN5", ambito=self.produttivo)
        self.gruppo = AccessGroup.objects.create(code="v8-operatori-sintetico", label="Profilo sintetico operatori v8")
        self.r_cn5.profili_permessi.add(self.gruppo)
        self.r_pe = RuoloOperativo.objects.create(nome="Project Engineer", ambito=self.produttivo)
        self.r_msm = RuoloOperativo.objects.create(nome="Management System Manager", ambito=self.produttivo)
        self.r_maint = RuoloOperativo.objects.create(nome="Maintenance Staff", ambito=self.produttivo)
        self.r_tnfr = RuoloOperativo.objects.create(nome="Dept Chief TNFR", ambito=self.produttivo)
        self.r_cmm = RuoloOperativo.objects.create(nome="CMM Specialist", ambito=self.produttivo)
        # Persone (sintetiche)
        self.p_cn5 = AnagraficaDipendente.objects.create(nome="A", cognome="VOTTO", aliasusername="v8.a")
        self.p_pe = AnagraficaDipendente.objects.create(nome="B", cognome="VOTTO", aliasusername="v8.b")
        self.p_man = AnagraficaDipendente.objects.create(nome="C", cognome="VOTTO", aliasusername="v8.c")
        self.p_car = AnagraficaDipendente.objects.create(nome="D", cognome="VOTTO", aliasusername="v8.d")
        _assegna(self.p_cn5, self.r_cn5)
        _assegna(self.p_pe, self.r_pe)
        DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=self.p_pe.pk).update(
            area="UT", area_aziendale=self.a_in1)
        _assegna(self.p_man, self.r_maint)
        DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=self.p_man.pk).update(
            area="LOGISTICA", area_aziendale=self.a_manut)
        _assegna(self.p_car, self.r_tnfr)
        # Mansioni di oggi
        self.asset_mk1 = Asset.objects.create(name="MIKRON sintetica", asset_tag="CNC-MK1- 1", reparto="CN5")
        self.mk1 = CompetenzaSkm.objects.create(competenza_key="MK1", display="MK1 - MIKRON HSM 600U",
                                                tipo=CompetenzaSkm.TIPO_MACCHINA, asset=self.asset_mk1)
        self.asset_dm16 = Asset.objects.create(name="DMC 85 H DM16 MONOBLOCK", asset_tag="CNC-DM16- 2")
        self.marcatura = CompetenzaSkm.objects.create(competenza_key="Marcatura", display="Marcatura",
                                                      tipo=CompetenzaSkm.TIPO_PROCESSO)
        self.aero = CompetenzaSkm.objects.create(competenza_key="Montaggio per aeronautica",
                                                 display="Montaggio per aeronautica", tipo=CompetenzaSkm.TIPO_PROCESSO)
        self.muletto = CompetenzaSkm.objects.create(competenza_key="Muletto", display="Muletto",
                                                    tipo=CompetenzaSkm.TIPO_PROCESSO)
        for nome in ("ADDETTO UFFICI", "ADDETTO MACCHINE UTENSILI", "ADDETTO AGGIUSTAGGIO"):
            Mansione.objects.get_or_create(nome=nome)


class CaricamentoV8Tests(_Base):
    def test_prova_non_scrive_niente(self):
        r = struttura_v8.carica(applica=False, user=self.user)
        self.assertFalse(r.applicato)
        self.assertTrue(r.righe)
        self.assertFalse(Reparto.objects.filter(nome="CN5G").exists())
        self.assertTrue(RuoloOperativo.objects.get(pk=self.r_cn5.pk).is_active)
        self.assertFalse(CompetenzaSkm.objects.filter(area__isnull=False).exists())

    def test_applica_reparti_e_aree(self):
        struttura_v8.carica(applica=True, user=self.user)
        self.alesatrici.refresh_from_db()
        self.assertEqual(self.alesatrici.nome, "CN5G")  # rinominato, stesso reparto
        self.assertTrue(Reparto.objects.filter(nome="TNF").exists())
        self.assertTrue(Reparto.objects.filter(nome="TORNI").exists())
        self.a_alesatrici.refresh_from_db()
        self.assertEqual(self.a_alesatrici.nome, "ALC")
        ut = AreaAziendale.objects.get(nome="UFFICIO TECNICO")
        self.assertEqual(ut.pk, self.a_in1.pk)  # IN1 rinominata in UFFICIO TECNICO
        self.assertEqual(ut.ruolo_responsabile.sigla, "EM")
        self.assertEqual(AreaAziendale.objects.get(nome="COMMERCIALE").pk, self.a_vendite.pk)
        hse = AreaAziendale.objects.get(nome="HSE")
        self.assertEqual(hse.reparto.nome, "UT")
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.p_man.pk)
        self.assertEqual(az.area_aziendale_id, hse.pk)  # il manutentore segue l'area in HSE
        self.assertEqual(az.area, "UT")

    def test_applica_ruoli_accorpati_senza_perdere_permessi(self):
        struttura_v8.carica(applica=True, user=self.user)
        omu = RuoloOperativo.objects.get(nome="Operatore Macchina Utensile")
        self.assertEqual(omu.pk, self.r_cnc.pk)  # il ruolo di oggi più numeroso è rinominato
        self.assertIn(self.gruppo, omu.profili_permessi.all())  # i permessi di Operatore CN5 passano
        self.r_cn5.refresh_from_db()
        self.assertFalse(self.r_cn5.is_active)
        self.assertIn("Operatore CN5", omu.nomi_precedenti)
        vecchia = DipendenteRuoloOperativo.objects.get(legacy_anagrafica_id=self.p_cn5.pk, ruolo=self.r_cn5)
        self.assertIsNotNone(vecchia.data_fine)  # il periodo resta nello storico
        nuova = DipendenteRuoloOperativo.objects.get(legacy_anagrafica_id=self.p_cn5.pk, ruolo=omu)
        self.assertIsNone(nuova.data_fine)
        self.assertEqual(nuova.tipologia, DipendenteRuoloOperativo.TIPOLOGIA_PRINCIPALE)
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.p_cn5.pk)
        self.assertEqual(az.ruolo_aziendale, "Operatore Macchina Utensile")
        self.assertEqual(az.area_aziendale.nome, "CN5")  # area dal ruolo di oggi
        self.r_msm.refresh_from_db()
        self.assertEqual((self.r_msm.sigla, self.r_msm.classe), ("MSM", RuoloOperativo.CLASSE_INDIRETTO))
        self.r_cmm.refresh_from_db()
        self.assertFalse(self.r_cmm.is_active)
        car = RuoloOperativo.objects.get(sigla="CAR")
        self.assertEqual(car.nome, "Caporeparto")
        self.assertEqual(Reparto.objects.get(nome="TNF").caporeparto_legacy_id, self.p_car.pk)

    def test_applica_processi_e_mansioni(self):
        from sistema_gestione.models import Processo

        struttura_v8.carica(applica=True, user=self.user)
        self.assertEqual(Processo.objects.count(), 9)
        prd = Processo.objects.get(codice="PRC-PRD")
        self.assertEqual((prd.tipo, prd.ruolo_owner.sigla), ("PRINCIPALE", "OPM"))
        self.assertTrue(prd.revisioni.exists())
        self.aero.refresh_from_db()
        self.assertEqual(self.aero.display, "Montaggio 9100")  # rinomina 1:1, stessa riga
        self.marcatura.refresh_from_db()
        self.assertFalse(self.marcatura.attiva)
        laser = CompetenzaSkm.objects.get(display="Marcatura laser")
        self.assertEqual(laser.deriva_da_id, self.marcatura.pk)
        self.mk1.refresh_from_db()
        self.assertEqual((self.mk1.area.nome, self.mk1.reparto.nome), ("CN5", "CN5"))
        self.assertEqual(self.mk1.processo_sgi_id, prd.pk)
        self.assertEqual(list(self.mk1.ruoli.values_list("nome", flat=True)), ["Operatore Macchina Utensile"])
        dm16 = CompetenzaSkm.objects.get(competenza_key="DM16")
        self.assertEqual(dm16.asset_id, self.asset_dm16.pk)
        self.assertTrue(CompetenzaSkm.objects.get(display="Liquidi penetranti").abilitazione_con_scadenza)
        self.muletto.refresh_from_db()
        self.assertTrue(self.muletto.attiva)  # in sospeso: non si tocca
        resp = CompetenzaSkm.objects.get(responsabilita_reparto__nome="CN5")
        self.assertEqual(resp.display, "Responsabilità del reparto CN5")
        self.assertEqual(list(resp.ruoli.values_list("sigla", flat=True)), ["CAR"])

    def test_secondo_giro_non_cambia_niente(self):
        struttura_v8.carica(applica=True, user=self.user)
        r = struttura_v8.carica(applica=True, user=self.user)
        cambi = [x for x in r.righe if x.azione in ("crea", "rinomina", "accorpa", "sposta", "spegne", "aggiorna")]
        self.assertEqual(cambi, [], [f"{x.fase} {x.azione} {x.oggetto} {x.dettaglio}" for x in cambi])

    def test_rischi_proposti_non_confermati(self):
        struttura_v8.carica(applica=True, user=self.user)
        ufficio = Mansione.objects.get(nome="ADDETTO UFFICI")
        m = CompetenzaSkm.objects.get(display__startswith="Riesame tecnico dell")
        self.assertEqual(list(m.mansioni_rischio_proposte.all()), [ufficio])
        self.assertFalse(m.mansioni_rischio.exists())  # vale solo dopo la conferma HSE
        rischi.conferma(m, [ufficio.pk])
        self.assertEqual(list(m.mansioni_rischio.all()), [ufficio])
        self.assertFalse(m.mansioni_rischio_proposte.exists())


class AccorpaRuoloTests(_Base):
    def test_doppioni_e_gerarchia(self):
        q = TipoQualifica.objects.create(nome="Patentino sintetico v8")
        RuoloQualifica.objects.create(ruolo=self.r_cn5, qualifica=q)
        RuoloQualifica.objects.create(ruolo=self.r_cnc, qualifica=q)
        figlio = RuoloOperativo.objects.create(nome="Allievo sintetico", riporta_a=self.r_cn5)
        esito = struttura_ruoli.accorpa(self.r_cn5, self.r_cnc, user=self.user)
        self.assertEqual(esito["doppioni"], 1)
        self.assertEqual(RuoloQualifica.objects.filter(ruolo=self.r_cnc).count(), 1)
        figlio.refresh_from_db()
        self.assertEqual(figlio.riporta_a_id, self.r_cnc.pk)

    def test_rinomina_riscrive_la_scheda(self):
        struttura_ruoli.rinomina(self.r_pe, "Ingegnere sintetico", sigla="ins")
        self.r_pe.refresh_from_db()
        self.assertEqual((self.r_pe.sigla, self.r_pe.nomi_precedenti), ("INS", "Project Engineer"))
        self.assertEqual(DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.p_pe.pk).ruolo_aziendale,
                         "Ingegnere sintetico")

    def test_sigla_unica(self):
        struttura_ruoli.rinomina(self.r_pe, self.r_pe.nome, sigla="IN1")
        with self.assertRaises(ValueError):
            struttura_ruoli.rinomina(self.r_cnc, self.r_cnc.nome, sigla="in1")


class RevisioniTests(_Base):
    def _come_msm(self):
        self.r_msm.sigla = "MSM"
        self.r_msm.save()
        return mock.patch("core.operational_roles.get_roles_for_user",
                          return_value=RuoloOperativo.objects.filter(pk=self.r_msm.pk))

    def test_solo_msm_emette(self):
        with mock.patch("core.operational_roles.get_roles_for_user", return_value=RuoloOperativo.objects.none()):
            self.assertFalse(rev.puo_emettere(self.user))  # nemmeno l'amministratore
            with self.assertRaises(PermissionError):
                rev.emetti(self.user, "prova")
        with self._come_msm():
            r1 = rev.emetti(self.user, "Prima emissione")
        self.assertEqual(r1.numero, 1)
        self.assertNotIn("VOTTO", str(r1.dati))  # nessun nominativo nella fotografia

    def test_niente_da_emettere_e_confronto(self):
        with self._come_msm():
            r1 = rev.emetti(self.user, "Prima")
            with self.assertRaises(ValueError):
                rev.emetti(self.user, "Uguale")
            self.r_pe.sigla = "IN1"
            self.r_pe.save()
            r2 = rev.emetti(self.user, "Sigla IN1")
        diff = rev.confronto(r1.dati, r2.dati)
        self.assertEqual(diff[0]["sezione"], "Ruoli")
        self.assertEqual(diff[0]["cambiate"][0]["campi"][0]["dopo"], "IN1")
        self.assertTrue(rev.pdf(r2).startswith(b"%PDF"))
        self.assertEqual(StrutturaRevisione.objects.count(), 2)


class ResponsabilitaRepartoTests(_Base):
    def test_segue_il_ruolo_responsabile(self):
        car = RuoloOperativo.objects.create(nome="Caporeparto sintetico", sigla="CARX")
        self.ut.ruolo_responsabile = car
        self.ut.save()
        m, _ = struttura_v8.assicura_responsabilita(self.ut)
        self.assertTrue(m.attiva)
        self.ut.ruolo_responsabile = None
        self.ut.save()
        m2, _ = struttura_v8.assicura_responsabilita(self.ut)
        self.assertEqual(m.pk, m2.pk)
        self.assertFalse(m2.attiva)  # spenta, non cancellata
        self.assertEqual(CompetenzaSkm.objects.filter(responsabilita_reparto=self.ut).count(), 1)
