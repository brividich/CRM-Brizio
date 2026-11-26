"""Coerenza formazione/qualifiche (analisi 26/11/2026, punti 2, 4, 5, 9, 12, 14). Dati sintetici.

- soglie uniche 30/90 (scadenze_soglie) in scadenzario, cruscotto, modello qualifica;
  le visite mediche restano a 60 giorni;
- ex dipendenti fuori da Lacune, Matrice competenze e Matrice qualifiche;
- Copertura onesta: «Nessun obbligo configurato» invece di «Tutti in regola»;
- «Obbligatorio per tutti» (TrainingCourse.obbligatorio) come fonte di obbligo del motore;
- Matrice qualifiche: «mancante» solo se richiesta;
- Copertura macchine: soglie gestite dal portale, abilitati coerenti col Mansionario.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset
from core.legacy_models import AnagraficaDipendente

from .models import (
    AbilitazioneMacchina,
    CompetenzaSkm,
    DipendenteAnagraficaAziendale,
    DipendenteQualifica,
    DipendenteRuoloOperativo,
    LivelloSkm,
    RuoloOperativo,
    RuoloQualifica,
    SkillMatrixConfig,
    SogliaCopertura,
    TipoQualifica,
)
from .models_formazione import TrainingCourse, TrainingDeadline, TrainingPlan
from .scadenze_soglie import GIORNI_PREAVVISO
from .services import cruscotto_hr
from .services import mansionario_competenze as comp
from .services import mansionario_struttura as svc
from .tests import _ensure_anagrafica_table

User = get_user_model()
_OVR = dict(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)


def _oggi():
    return timezone.localdate()


class SoglieUnicheTests(TestCase):
    def test_qualifica_in_scadenza_entro_90_giorni(self):
        tipo = TipoQualifica.objects.create(nome="Patentino sintetico S1")
        q75 = DipendenteQualifica(legacy_anagrafica_id=1, tipo=tipo, data_scadenza=_oggi() + timedelta(days=75))
        q120 = DipendenteQualifica(legacy_anagrafica_id=1, tipo=tipo, data_scadenza=_oggi() + timedelta(days=120))
        self.assertEqual(GIORNI_PREAVVISO, 90)
        self.assertTrue(q75.in_scadenza)
        self.assertFalse(q120.in_scadenza)

    def test_cruscotto_formazione_90_visite_60(self):
        oggi = _oggi()
        self.assertEqual(cruscotto_hr._tono_scadenza(oggi + timedelta(days=75), oggi), "warn")
        self.assertEqual(
            cruscotto_hr._tono_scadenza(oggi + timedelta(days=75), oggi, cruscotto_hr.SOGLIA_GIORNI_VISITE), "")


@override_settings(**_OVR)
class ScadenzarioUnificatoSoglieTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("ag3_scad", "ag3s@example.invalid", "x")
        self.client.force_login(self.admin)
        self.p = AnagraficaDipendente.objects.create(nome="DUE", cognome="ESEMPIO", aliasusername="esempio.due.ag3")
        self.tipo = TipoQualifica.objects.create(nome="Abilitazione sintetica S2")
        DipendenteQualifica.objects.create(legacy_anagrafica_id=self.p.pk, tipo=self.tipo,
                                           data_conseguimento=_oggi() - timedelta(days=300),
                                           data_scadenza=_oggi() + timedelta(days=75))

    def test_qualifica_a_75_giorni_e_in_scadenza(self):
        url = reverse("anagrafica:scadenzario")
        for qs in ("", "?stato=90", "?stato=60"):  # «60» resta l'alias dei link storici
            resp = self.client.get(url + qs)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.context["totale"], 1, qs)
        self.assertEqual(self.client.get(url + "?stato=30").context["totale"], 0)
        self.assertEqual(self.client.get(url).context["n_60gg"], 1)


@override_settings(**_OVR)
class CessatiFuoriTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        SkillMatrixConfig.get_instance()
        asset = Asset.objects.create(name="Fresa sintetica AG3", reparto="FRESE")
        self.mansione = CompetenzaSkm.objects.create(competenza_key="AG3-FR", display="Fresa AG3",
                                                     tipo=CompetenzaSkm.TIPO_MACCHINA, asset=asset)
        comp.salva_competenza(self.mansione, nome="Set-up AG3", livello_minimo="U", bloccante=True)
        self.attivo = AnagraficaDipendente.objects.create(nome="TRE", cognome="ESEMPIO", aliasusername="esempio.tre.ag3")
        self.ex = AnagraficaDipendente.objects.create(nome="QUATTRO", cognome="ESEMPIO", aliasusername="esempio.quattro.ag3")
        svc.assegna(self.mansione, legacy_anagrafica_id=self.attivo.pk, livello="I")
        svc.assegna(self.mansione, legacy_anagrafica_id=self.ex.pk, livello="I")
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=self.ex.pk, data_cessazione=date(2025, 12, 31))

    def test_lacune_senza_ex_dipendenti(self):
        ids = {r["legacy_id"] for r in comp.lacune()}
        self.assertIn(self.attivo.pk, ids)
        self.assertNotIn(self.ex.pk, ids)

    def test_matrice_competenze_senza_ex_dipendenti(self):
        from .services import competenze_catalogo as cat

        ids = {r["legacy_id"] for r in cat.matrice()["righe"]}
        self.assertNotIn(self.ex.pk, ids)

    def test_pagina_lacune_titolo_e_legenda(self):
        admin = User.objects.create_superuser("ag3_lac", "ag3l@example.invalid", "x")
        self.client.force_login(admin)
        resp = self.client.get(reverse("anagrafica:mansionario_lacune"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Lacune di mansione")
        self.assertContains(resp, "Formatore/Esperto")


@override_settings(**_OVR)
class CoperturaOnestaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("ag3_cop", "ag3c@example.invalid", "x")
        self.client.force_login(self.admin)
        self.p = AnagraficaDipendente.objects.create(nome="CINQUE", cognome="ESEMPIO", aliasusername="esempio.cinque.ag3",
                                                     reparto="Officina")
        self.piano = TrainingPlan.objects.create(codice="P-AG3", nome="Piano AG3")

    def test_nessun_obbligo_non_dice_tutti_in_regola(self):
        resp = self.client.get(reverse("anagrafica:formazione_copertura"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["nessun_obbligo"])
        self.assertContains(resp, "Nessun obbligo configurato")
        self.assertNotContains(resp, "Tutti in regola")

    def test_corso_obbligatorio_per_tutti_e_un_obbligo_del_motore(self):
        corso = TrainingCourse.objects.create(piano=self.piano, codice="C-AG3-TUTTI", titolo="Corso per tutti AG3",
                                              durata_ore_teorica=2, obbligatorio=True)
        from .services import requisiti

        ctx = requisiti.ambito(_oggi())
        persone = {p.id: p for p in ctx._tutti() if p.in_forza_al(_oggi())}
        richiesti = requisiti.requisiti_formazione(ctx, persone)
        self.assertIn(corso.pk, richiesti[self.p.pk])
        self.assertIn(requisiti.ORIGINE_OBBLIGATORIO_TUTTI, richiesti[self.p.pk][corso.pk])

        resp = self.client.get(reverse("anagrafica:formazione_copertura"))
        self.assertFalse(resp.context["nessun_obbligo"])
        self.assertContains(resp, "Corso per tutti AG3")
        self.assertIn("n_in_scadenza", resp.context)

    def test_scadenzario_formazione_di_default_solo_obbligatori(self):
        obb = TrainingCourse.objects.create(piano=self.piano, codice="C-AG3-O", titolo="Obbligo AG3", durata_ore_teorica=2)
        fac = TrainingCourse.objects.create(piano=self.piano, codice="C-AG3-F", titolo="Facoltativo AG3", durata_ore_teorica=2)
        TrainingDeadline.objects.create(corso=obb, legacy_anagrafica_id=self.p.pk, stato_scadenza="SCADUTO", is_required=True)
        TrainingDeadline.objects.create(corso=fac, legacy_anagrafica_id=self.p.pk, stato_scadenza="SCADUTO", is_required=False)
        url = reverse("anagrafica:formazione_scadenzario")
        resp = self.client.get(url)
        self.assertTrue(resp.context["filtro_obbligatori"])
        self.assertEqual((resp.context["totale"], resp.context["n_scaduti"]), (1, 1))
        tutti = self.client.get(url + "?obbligatori=0")
        self.assertEqual((tutti.context["totale"], tutti.context["n_scaduti"]), (2, 2))

    def test_form_corso_etichetta_obbligatorio_per_tutti(self):
        from .forms import TrainingCourseForm

        self.assertEqual(TrainingCourseForm().fields["obbligatorio"].label, "Obbligatorio per tutti i dipendenti")


@override_settings(**_OVR)
class MatriceQualificheTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("ag3_mq", "ag3mq@example.invalid", "x")
        self.client.force_login(self.admin)
        self.richiesta = TipoQualifica.objects.create(nome="Qualifica richiesta AG3")
        self.posseduta = TipoQualifica.objects.create(nome="Qualifica posseduta AG3")
        ruolo = RuoloOperativo.objects.create(nome="Ruolo sintetico AG3")
        RuoloQualifica.objects.create(ruolo=ruolo, qualifica=self.richiesta, obbligatoria=True)
        self.a = AnagraficaDipendente.objects.create(nome="SEI", cognome="ESEMPIO", aliasusername="esempio.sei.ag3")
        self.b = AnagraficaDipendente.objects.create(nome="SETTE", cognome="ESEMPIO", aliasusername="esempio.sette.ag3")
        self.ex = AnagraficaDipendente.objects.create(nome="OTTO", cognome="ESEMPIO", aliasusername="esempio.otto.ag3")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=self.a.pk, ruolo=ruolo)
        DipendenteQualifica.objects.create(legacy_anagrafica_id=self.b.pk, tipo=self.posseduta,
                                           data_conseguimento=_oggi() - timedelta(days=10))
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=self.ex.pk, data_cessazione=date(2025, 12, 31))

    def test_mancante_solo_se_richiesta(self):
        resp = self.client.get(reverse("anagrafica:matrice_competenze"))
        self.assertEqual(resp.status_code, 200)
        colonne = [t.pk for t in resp.context["tipi"]]
        self.assertEqual(set(colonne), {self.richiesta.pk, self.posseduta.pk})
        righe = {r["legacy_id"]: r for r in resp.context["righe"]}
        self.assertNotIn(self.ex.pk, righe)
        stato_a = {c["tipo_id"]: c["stato"] for c in righe[self.a.pk]["celle"]}
        stato_b = {c["tipo_id"]: c["stato"] for c in righe[self.b.pk]["celle"]}
        self.assertEqual(stato_a[self.richiesta.pk], "mancante")
        self.assertEqual(stato_a[self.posseduta.pk], "non_richiesta")
        self.assertEqual(stato_b[self.richiesta.pk], "non_richiesta")
        self.assertEqual(stato_b[self.posseduta.pk], "valido")
        self.assertContains(resp, "Matrice qualifiche")


@override_settings(**_OVR)
class CoperturaMacchineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        SkillMatrixConfig.get_instance()
        self.admin = User.objects.create_superuser("ag3_skm", "ag3k@example.invalid", "x")
        self.client.force_login(self.admin)
        self.url = reverse("anagrafica:skm_copertura")
        self.asset = Asset.objects.create(asset_tag="CNC-AG3", name="Centro sintetico AG3", asset_type="CNC")
        self.mansione = CompetenzaSkm.objects.create(competenza_key="AG3-CNC", display="CNC AG3",
                                                     tipo=CompetenzaSkm.TIPO_MACCHINA, asset=self.asset)

    def test_aggiungi_modifica_elimina_soglia(self):
        resp = self.client.post(self.url, {"azione": "salva", "nome": "Copertura AG3", "asset": self.asset.pk,
                                           "livello_minimo": "U", "minimo_abilitati": "2"})
        self.assertEqual(resp.status_code, 302)
        soglia = SogliaCopertura.objects.get(nome="Copertura AG3")
        self.client.post(self.url, {"azione": "salva", "soglia_id": soglia.pk, "nome": "Copertura AG3 bis",
                                    "asset": self.asset.pk, "livello_minimo": "U", "minimo_abilitati": "3"})
        soglia.refresh_from_db()
        self.assertEqual((soglia.nome, soglia.minimo_abilitati), ("Copertura AG3 bis", 3))
        self.client.post(self.url, {"azione": "elimina", "soglia_id": soglia.pk})
        self.assertFalse(SogliaCopertura.objects.filter(pk=soglia.pk).exists())

    def test_soglia_senza_target_non_salvata(self):
        resp = self.client.post(self.url, {"azione": "salva", "nome": "Senza target", "livello_minimo": "U",
                                           "minimo_abilitati": "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(SogliaCopertura.objects.filter(nome="Senza target").exists())

    def test_abilitato_senza_requisito_formale_non_conta(self):
        from .services import skillmatrix_copertura as cov

        patentino = TipoQualifica.objects.create(nome="Patentino sintetico AG3")
        voce = comp.salva_competenza(self.mansione, nome="Uso CNC AG3", livello_minimo="U", qualifica_id=patentino.pk)
        p1 = AnagraficaDipendente.objects.create(nome="NOVE", cognome="ESEMPIO", aliasusername="esempio.nove.ag3")
        p2 = AnagraficaDipendente.objects.create(nome="DIECI", cognome="ESEMPIO", aliasusername="esempio.dieci.ag3")
        for p in (p1, p2):
            ab = AbilitazioneMacchina.objects.create(legacy_anagrafica_id=p.pk, asset=self.asset,
                                                     competenza=self.mansione, livello=LivelloSkm.AUTONOMO)
            ab.voci.create(voce=voce, livello="U")
        DipendenteQualifica.objects.create(legacy_anagrafica_id=p1.pk, tipo=patentino,
                                           data_scadenza=_oggi() + timedelta(days=200))
        soglia = SogliaCopertura.objects.create(nome="Copertura req AG3", asset=self.asset, minimo_abilitati=2,
                                                livello_minimo=LivelloSkm.AUTONOMO)
        r = cov.valuta_soglia(soglia)
        self.assertEqual((r["disponibili"], r["gap"]), (1, 1))
