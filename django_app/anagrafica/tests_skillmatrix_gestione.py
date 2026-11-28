"""Skill Matrix: matrice per reparto con CAR, scheda della cella, azioni ed export
(Excel, PDF «Report HUB», PDF «MOD.187»). Dati sintetici."""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset
from core.legacy_models import AnagraficaDipendente

from .models import (AbilitazioneMacchina, AbilitazioneMacchinaStorico, CompetenzaSkm, ProfiloMansioniPersona,
                     Reparto)
from .services import skillmatrix_vista as vista
from .tests import _ensure_anagrafica_table

User = get_user_model()


@override_settings(SECURE_SSL_REDIRECT=False, LEGACY_AUTH_ENABLED=False)
class SkillMatrixGestioneTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("skg", "skg@example.invalid", "x")
        self.client.force_login(self.admin)
        self.url = reverse("anagrafica:skill_matrix_macchina")
        self.car = AnagraficaDipendente.objects.create(cognome="CAPO", nome="ANNA", aliasusername="skg.capo")
        self.op = AnagraficaDipendente.objects.create(cognome="OPERAIO", nome="BRUNO", aliasusername="skg.op")
        self.rep = Reparto.objects.create(nome="CN5G", caporeparto_legacy_id=self.car.pk)
        self.macchine = []
        for nome in ("DM10 - DMC 85", "DM3 - DMC 85"):
            a = Asset.objects.create(asset_tag=f"SKG-{nome[:4]}", name=nome, asset_type="CNC", reparto="CN5G")
            self.macchine.append(CompetenzaSkm.objects.create(competenza_key=f"skg_{nome[:4]}", display=nome,
                                                              tipo="macchina", asset=a))
        self.proc = CompetenzaSkm.objects.create(competenza_key="skg_presetting", display="Presetting",
                                                 tipo="processo", reparto=self.rep)
        m10, m3 = self.macchine
        self.ab = AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.op.pk, asset=m3.asset, competenza=m3,
                                                      livello="L", prossima_revisione=date.today() - timedelta(days=3))
        AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.car.pk, asset=m10.asset, competenza=m10, livello="O")
        AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.car.pk, competenza=self.proc, livello="U")

    def test_matrice_per_reparto_car_per_primo_e_ordine_naturale(self):
        d = vista.costruisci()
        self.assertEqual([c["nome"] for c in d["colonne"]], ["DM3 - DMC 85", "DM10 - DMC 85", "Presetting"])
        self.assertEqual(d["gruppi_colonne"][0]["car"], "Capo Anna")
        self.assertEqual([r["nome_mod"] for r in d["righe"]], ["CAPO ANNA", "OPERAIO BRUNO"])
        self.assertEqual(d["righe"][0]["ruolo"], "CAR CN5G")
        self.assertEqual(d["colonne"][0]["conta"]["L"], 1)
        self.assertEqual(d["n_rivalutare"], 1)
        self.assertEqual([r["lid"] for r in vista.costruisci(solo="rivalutare")["righe"]], [self.op.pk])
        self.assertNotIn("Presetting", [c["nome"] for c in vista.costruisci(solo_macchine=True)["colonne"]])

    def test_pagina_e_scheda(self):
        r = self.client.get(self.url)
        self.assertContains(r, "CAR")
        self.assertContains(r, "PDF · MOD.187")
        m3 = self.macchine[1]
        r = self.client.get(reverse("anagrafica:skm_scheda"), {"lid": self.op.pk, "comp": m3.pk})
        self.assertContains(r, "Cambia livello")
        self.assertContains(r, "scaduta")

    def _azione(self, **dati):
        dati.setdefault("lid", self.op.pk)
        dati.setdefault("comp", self.macchine[1].pk)
        return self.client.post(reverse("anagrafica:skm_azione"), dati)

    def test_cambia_livello_vuole_il_motivo_e_lo_storicizza(self):
        self._azione(azione="livello", livello="U")
        self.ab.refresh_from_db()
        self.assertEqual(self.ab.livello, "L")
        r = self._azione(azione="livello", livello="U", motivo="prova pratica superata")
        self.assertIn("apri=", r["Location"])
        self.ab.refresh_from_db()
        self.assertEqual(self.ab.livello, "U")
        self.assertIn("prova pratica superata",
                      AbilitazioneMacchinaStorico.objects.filter(legacy_anagrafica_id=self.op.pk).latest("id").note)

    def test_abilita_sospendi_togli_orario_revisione(self):
        m10 = self.macchine[0]
        self._azione(azione="abilita", comp=m10.pk, livello="I", motivo="affiancamento")
        nuova = AbilitazioneMacchina.objects.get(legacy_anagrafica_id=self.op.pk, asset=m10.asset)
        self.assertEqual(nuova.livello, "I")
        self._azione(azione="sospendi")
        self.ab.refresh_from_db()
        self.assertEqual(self.ab.stato, "sospesa")
        self._azione(azione="togli", motivo="cambio reparto")
        self.ab.refresh_from_db()
        self.assertFalse(self.ab.in_lista)
        self._azione(azione="orario", orario="T2")
        self.assertEqual(ProfiloMansioniPersona.objects.get(legacy_anagrafica_id=self.op.pk).orario, "T2")
        self.client.post(reverse("anagrafica:skm_azione"), {"azione": "revisione_blocco", "persone": f"{self.op.pk}",
                                                            "data": "2027-05-31"})
        nuova.refresh_from_db()
        self.assertEqual(nuova.prossima_revisione, date(2027, 5, 31))

    def test_senza_permesso_di_gestione_niente_modifiche(self):
        semplice = User.objects.create_user("skg_u", "u@example.invalid", "x")
        self.client.force_login(semplice)
        self._azione(azione="livello", livello="O", motivo="x")
        self.ab.refresh_from_db()
        self.assertEqual(self.ab.livello, "L")

    def test_export_excel_e_pdf(self):
        r = self.client.get(self.url, {"format": "xlsx"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("spreadsheetml", r["Content-Type"])
        for formato in ("pdf_hub", "pdf_mod"):
            r = self.client.get(self.url, {"format": formato})
            self.assertEqual(r["Content-Type"], "application/pdf")
            self.assertTrue(r.content.startswith(b"%PDF"))
        r = self.client.get(self.url, {"format": "csv", "persone": str(self.op.pk)})
        testo = r.content.decode("utf-8-sig")
        self.assertIn("Operaio Bruno", testo)
        self.assertNotIn("Capo Anna", testo)

    def test_pdf_mod_con_molte_colonne_va_su_piu_fogli(self):
        import fitz
        rep = Reparto.objects.create(nome="ALTRO")
        for i in range(140):
            c = CompetenzaSkm.objects.create(competenza_key=f"skg_p{i}", display=f"Processo {i}", tipo="processo", reparto=rep)
            AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.op.pk, competenza=c, livello="U")
        r = self.client.get(self.url, {"format": "pdf_mod"})
        self.assertGreaterEqual(fitz.open(stream=r.content, filetype="pdf").page_count, 2)
