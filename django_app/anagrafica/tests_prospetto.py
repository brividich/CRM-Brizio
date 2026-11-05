"""Prospetto dei cambiamenti: niente si scrive prima, e il «Dopo» simulato è quello vero dopo l'applicazione.

Scenario di ``tests_capo_team``: rossi (IN1), bianchi (IN2), neri e verdi (SA1), gialli senza area.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from .exports import EXPORT_SPECS
from .models import (
    AbilitazioneMacchina, CentroDiCosto, CostoOrarioMensile, DipendenteAnagraficaAziendale, DipendenteAssegnazione,
    DipendenteRuoloOperativo, SkillMatrixConfig,
)
from .models_skillmatrix import CompetenzaSkm
from .models_struttura import ProspettoModifica as M
from .models_struttura import ProspettoStruttura as P
from .reportistica import sezioni as catalogo
from .reportistica.dati import SENZA_CENTRO, Contesto, Perimetro
from .services import capo_team, mansionario_struttura as mstr
from .services import prospetto_struttura as svc
from .tests_capi_mansione import _ScenarioMansioni

User = get_user_model()


class _Base(_ScenarioMansioni):
    def setUp(self):
        super().setUp()
        self.oggi = timezone.localdate()
        self.lav = CentroDiCosto.objects.create(nome="LAVORAZIONI")
        self.sal = CentroDiCosto.objects.create(nome="SALDATURE")
        for area, c in ((self.in1, self.lav), (self.in2, self.lav), (self.sa1, self.sal)):
            area.centro_di_costo = c
            area.save(update_fields=["centro_di_costo"])
        self.m1 = self._crea("Fresa F1", self.in1, self.op)
        self.m2 = self._crea("Taglio T1", self.sa1, self.op)
        self.m3 = self._crea("Taglio T2", self.sa1, self.op)
        SkillMatrixConfig.get_instance()
        mstr.assegna(self.m1, legacy_anagrafica_id=self.rossi, livello="U")
        mstr.assegna(self.m1, legacy_anagrafica_id=self.bianchi, livello="U")
        mstr.assegna(self.m2, legacy_anagrafica_id=self.verdi, livello="U")
        mstr.assegna(self.m3, legacy_anagrafica_id=self.verdi, livello="U")
        mstr.assegna(self.m3, legacy_anagrafica_id=self.neri, livello="L")
        for i, (pid, rml) in enumerate(((self.rossi, "3463.20"), (self.bianchi, "6926.40"), (self.verdi, "1731.60"))):
            CostoOrarioMensile.objects.create(
                tax_code=f"SNTTST80A01H50{i}Z", legacy_anagrafica_id=pid, mese=self.oggi.replace(day=1), rml=D(rml),
                divisore_giorni=D("26"), divisore_ore=D("6.66"), costo_orario=(D(rml) / D("173.16")).quantize(D("0.0001")))
        self.admin = User.objects.create_superuser("pro_admin", "pro@example.invalid", "x")
        self.client.force_login(self.admin)
        self.p = P.objects.create(nome="Prova", creato_da=self.admin)

    def _crea(self, nome, area, ruolo):
        m = CompetenzaSkm.objects.create(competenza_key=nome.lower().replace(" ", "_"), display=nome,
                                         tipo=CompetenzaSkm.TIPO_PROCESSO, area=area)
        m.ruoli.add(ruolo)
        return m

    def riga(self, tipo, soggetto, destinazione=None, **kw):
        return M.objects.create(prospetto=self.p, tipo=tipo, soggetto_id=soggetto, destinazione_id=destinazione, **kw)

    def ctx(self, **kw):
        return svc.costruisci(self.p, **kw)

    def kpi(self, ctx):
        return {r["chiave"]: r for r in ctx["kpi"]}

    def centro(self, ctx, nome):
        return next(r for r in ctx["centri"] if r["voce"] == nome)

    def mansione(self, ctx, m):
        return next((r for r in ctx["mansioni"] if r["id"] == m.pk), None)


class NienteSiScriveTests(_Base):
    def test_il_confronto_non_cambia_il_database(self):
        self.riga(M.PERSONA_REPARTO, self.rossi, self.sa1.pk, modo=M.LASCIA)
        self.riga(M.REPARTO_CENTRO, self.in2.pk, self.sal.pk)
        self.riga(M.PERSONA_RUOLO, self.verdi, self.capo.pk, modo="aggiungi")
        self.riga(M.PERSONA_MANSIONE, self.verdi, self.m1.pk, modo=M.ENTRA, livello="U")
        self.riga(M.MANSIONE_REPARTO, self.m2.pk, self.in1.pk)
        prima = (DipendenteAssegnazione.objects.count(), AbilitazioneMacchina.objects.filter(in_lista=True).count(),
                 DipendenteRuoloOperativo.objects.count())
        self.ctx()
        self.assertEqual(prima, (DipendenteAssegnazione.objects.count(), AbilitazioneMacchina.objects.filter(in_lista=True).count(),
                                 DipendenteRuoloOperativo.objects.count()))
        self.assertEqual(DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.rossi).area_aziendale, self.in1)
        self.in2.refresh_from_db()
        self.m2.refresh_from_db()
        self.assertEqual((self.in2.centro_di_costo, self.m2.area), (self.lav, self.sa1))

    def test_senza_cambiamenti_oggi_e_dopo_coincidono(self):
        ctx = self.ctx()
        self.assertTrue(all(r["delta"] == 0 for r in ctx["kpi"]))
        self.assertFalse(any(r["cambia"] for r in ctx["centri"]))
        self.assertEqual((ctx["reparti"], ctx["mansioni"], ctx["persone"]), ([], [], []))


class CentriECostiTests(_Base):
    def test_spostare_un_reparto_sposta_persone_e_costi_e_il_totale_tiene(self):
        self.riga(M.REPARTO_CENTRO, self.in2.pk, self.sal.pk)
        ctx = self.ctx(requisiti=False)
        lav, sal = self.centro(ctx, "LAVORAZIONI"), self.centro(ctx, "SALDATURE")
        self.assertEqual((lav["persone_prima"], lav["persone_dopo"], sal["persone_prima"], sal["persone_dopo"]), (2, 1, 2, 3))
        self.assertEqual((lav["rml_prima"], lav["rml_dopo"], lav["rml_delta"]), (D("10389.60"), D("3463.20"), D("-6926.40")))
        self.assertEqual(sal["rml_dopo"], D("8658.00"))
        self.assertEqual(ctx["totali"]["rml"], ctx["totali"]["somma_rml_dopo"])
        self.assertEqual(sum(r["delta"] for r in ctx["centri"]), 0)
        self.assertEqual((lav["reparti_prima"], lav["reparti_dopo"]), (2, 1))

    def test_il_costo_medio_del_centro_cambia_con_chi_ci_sta(self):
        self.riga(M.REPARTO_CENTRO, self.in2.pk, self.sal.pk)
        lav = self.centro(self.ctx(requisiti=False), "LAVORAZIONI")
        self.assertEqual((lav["medio_prima"], lav["medio_dopo"]), (D("30.00"), D("20.00")))

    def test_stessi_numeri_del_report_per_centro(self):
        ctx = self.ctx(requisiti=False)
        rep = Contesto(date_from=self.oggi - timedelta(days=30), date_to=self.oggi, perimetro=Perimetro.from_dict({}), today=self.oggi)
        righe = {r["voce"]: r for r in catalogo.get("costo_orario_ripartito").calcola(rep, {"per": "centro_costo"}).righe}
        self.assertEqual(self.centro(ctx, "LAVORAZIONI")["rml_prima"], righe["LAVORAZIONI"]["rml"])
        self.assertEqual(self.centro(ctx, "SALDATURE")["rml_prima"], righe["SALDATURE"]["rml"])
        self.assertEqual(self.centro(ctx, SENZA_CENTRO)["persone_prima"], 1)


class MansioniTests(_Base):
    def test_stessi_operativi_e_teste_equivalenti_del_report(self):
        ctx_rep = Contesto(date_from=self.oggi, date_to=self.oggi, perimetro=Perimetro.from_dict({}), today=self.oggi)
        rep = {r["mansione"]: r for r in catalogo.get("copertura_mansioni").calcola(ctx_rep, {}).righe}
        base = svc.Base()
        mis = svc.misure(base, base.stato, soglia_mansioni=8, soglia_concentrazione=80, capi=capo_team.mappa_capi())
        for m in (self.m1, self.m2, self.m3):
            self.assertEqual(mis["per_mansione"][m.pk]["operativi"], rep[m.nome]["operativi"], m.nome)
        self.assertEqual(mis["per_mansione"][self.m2.pk]["stato"], "uomo solo")
        self.assertEqual(rep[self.m2.nome]["stato"], "uomo solo")
        ripartito = {r["voce"]: r for r in catalogo.get("costo_orario_ripartito").calcola(ctx_rep, {"per": "mansione"}).righe}
        self.assertEqual(svc.d_due(mis["per_mansione"][self.m1.pk]["fte"]), ripartito[self.m1.nome]["fte"])
        self.assertEqual(svc._euro(mis["per_mansione"][self.m1.pk]["rml"]), ripartito[self.m1.nome]["rml"])

    def test_chi_esce_lascia_la_mansione_scoperta(self):
        self.riga(M.PERSONA_MANSIONE, self.verdi, self.m2.pk, modo=M.TOGLI)
        ctx = self.ctx(requisiti=False)
        r = self.mansione(ctx, self.m2)
        self.assertEqual((r["operativi_prima"], r["operativi_dopo"], r["stato_prima"], r["stato_dopo"]), (1, 0, "uomo solo", "scoperta"))
        self.assertTrue(r["peggiora"])
        self.assertEqual((self.kpi(ctx)["scoperte"]["prima"], self.kpi(ctx)["scoperte"]["dopo"]), (0, 1))
        self.assertTrue(self.kpi(ctx)["scoperte"]["peggiora"])

    def test_chi_entra_toglie_il_rischio_uomo_solo(self):
        self.riga(M.PERSONA_MANSIONE, self.rossi, self.m2.pk, modo=M.ENTRA, livello="U")
        r = self.mansione(self.ctx(requisiti=False), self.m2)
        self.assertEqual((r["stato_prima"], r["stato_dopo"]), ("uomo solo", "ok"))
        self.assertTrue(r["migliora"])

    def test_sotto_la_soglia_non_conta_come_operativo(self):
        self.riga(M.PERSONA_MANSIONE, self.rossi, self.m2.pk, modo=M.ENTRA, livello="I")
        r = self.mansione(self.ctx(requisiti=False), self.m2)
        self.assertEqual((r["lista_dopo"], r["operativi_dopo"], r["stato_dopo"]), (2, 1, "uomo solo"))

    def test_entrando_i_coefficienti_si_ripartiscono(self):
        self.riga(M.PERSONA_MANSIONE, self.rossi, self.m2.pk, modo=M.ENTRA, livello="U")
        ctx = self.ctx(requisiti=False)
        self.assertEqual((self.mansione(ctx, self.m1)["fte_prima"], self.mansione(ctx, self.m1)["fte_dopo"]), (D("2.00"), D("1.50")))
        self.assertEqual(self.mansione(ctx, self.m2)["fte_dopo"], D("1.00"))

    def test_carico_concentrato(self):
        base = svc.Base()
        mis = svc.misure(base, base.stato, soglia_mansioni=8, soglia_concentrazione=80, capi={})
        self.assertEqual(mis["per_mansione"][self.m1.pk]["concentrazione"], 100)
        self.assertTrue(mis["per_mansione"][self.m1.pk]["concentrato"])
        alta = svc.misure(base, base.stato, soglia_mansioni=8, soglia_concentrazione=101, capi={})
        self.assertFalse(alta["per_mansione"][self.m1.pk]["concentrato"])

    def test_troppe_mansioni_e_persona_chiave_con_le_soglie(self):
        self.p.soglia_mansioni_persona = 2
        self.p.save()
        self.riga(M.PERSONA_MANSIONE, self.verdi, self.m1.pk, modo=M.ENTRA, livello="U")
        ctx = self.ctx(requisiti=False)
        self.assertEqual([(x["id"], x["n"]) for x in ctx["persone_su_troppe"]], [(self.verdi, 3)])
        self.assertTrue(any("passerebbe a 3 mansioni" in a["testo"] for a in ctx["avvisi"]))
        chiave = {x["id"]: x["mansioni"] for x in ctx["persone_chiave"]}
        self.assertEqual(sorted(chiave[self.verdi]), ["Taglio T1", "Taglio T2"])

    def test_persona_in_altro_reparto_lascia_o_tiene_le_mansioni(self):
        self.riga(M.PERSONA_REPARTO, self.verdi, self.in1.pk, modo=M.LASCIA)
        ctx = self.ctx(requisiti=False)
        self.assertEqual(self.mansione(ctx, self.m2)["stato_dopo"], "scoperta")
        p = next(r for r in ctx["persone"] if r["id"] == self.verdi)
        self.assertEqual(p["mansioni_tolte"], ["Taglio T1", "Taglio T2"])
        self.assertIn("Fresa F1", p["da_assegnare"])
        M.objects.all().delete()
        self.riga(M.PERSONA_REPARTO, self.verdi, self.in1.pk, modo=M.TIENE)
        ctx = self.ctx(requisiti=False)
        self.assertIsNone(self.mansione(ctx, self.m2))
        p = next(r for r in ctx["persone"] if r["id"] == self.verdi)
        self.assertEqual(p["fuori_reparto"], ["Taglio T1", "Taglio T2"])

    def test_cessato_in_lista_non_conta_e_si_segnala(self):
        AbilitazioneMacchina.objects.create(legacy_anagrafica_id=999999, competenza=self.m2, livello="U")
        ctx = self.ctx(requisiti=False)
        self.assertTrue(any("non più in forza" in a["testo"] for a in ctx["avvisi"]))


class CapiERuoliTests(_Base):
    def test_il_capo_cambia_e_si_vede_anche_chi_cambia_di_conseguenza(self):
        self.riga(M.PERSONA_REPARTO, self.rossi, self.sa1.pk, modo=M.TIENE)
        ctx = self.ctx(requisiti=False)
        r = next(x for x in ctx["persone"] if x["id"] == self.rossi)
        self.assertEqual(r["centro_dopo"], "SALDATURE")
        self.assertTrue(r["modificata"])

    def test_togliere_il_ruolo_del_capo_toglie_il_capo_a_chi_ne_dipende(self):
        self.riga(M.PERSONA_RUOLO, self.bianchi, self.capo.pk, modo="chiudi")
        ctx = self.ctx(requisiti=False)
        r = next(x for x in ctx["persone"] if x["id"] == self.rossi)
        self.assertFalse(r["modificata"])
        self.assertTrue(r["cambia_capo"])

    def test_ruolo_previsto_che_resta_scoperto(self):
        self.in1.ruoli_reparto.add(self.op)
        self.riga(M.PERSONA_REPARTO, self.rossi, self.sa1.pk, modo=M.TIENE)
        ctx = self.ctx(requisiti=False)
        self.assertEqual(self.kpi(ctx)["ruoli_scoperti"]["delta"], 1)
        self.assertTrue(any("non resterebbe nessuno" in a["testo"] for a in ctx["avvisi"]))

    def test_reparto_che_resta_vuoto(self):
        self.riga(M.PERSONA_REPARTO, self.rossi, self.sa1.pk, modo=M.TIENE)
        ctx = self.ctx(requisiti=False)
        self.assertTrue(next(r for r in ctx["reparti"] if r["voce"] == "IN1")["resta_vuoto"])
        self.assertEqual(len(next(r for r in ctx["reparti"] if r["voce"] == "SA1")["entrano"]), 1)

    def test_chi_resta_capo_si_segnala(self):
        mstr.assegna(self.resp_fres, legacy_anagrafica_id=self.bianchi, livello="U")
        self.riga(M.PERSONA_REPARTO, self.bianchi, self.sa1.pk, modo=M.LASCIA)
        ctx = self.ctx(requisiti=False)
        self.assertTrue(any("resta capo" in a["testo"] for a in ctx["avvisi"]))


class OstacoliTests(_Base):
    def test_reparto_senza_reparto_del_portale_si_blocca(self):
        from .models import AreaAziendale

        orfana = AreaAziendale.objects.create(nome="TNCG")
        self.riga(M.PERSONA_REPARTO, self.rossi, orfana.pk, modo=M.TIENE)
        ctx = self.ctx(requisiti=False)
        self.assertIn("non è in un reparto del portale", ctx["righe_modifiche"][0]["problema"])
        self.assertFalse(any(r["cambia_reparto"] for r in ctx["persone"]))

    def test_soggetti_spariti_non_rompono(self):
        self.riga(M.PERSONA_REPARTO, 999999, self.in1.pk, modo=M.TIENE)
        self.riga(M.REPARTO_CENTRO, 999999, self.lav.pk)
        self.riga(M.MANSIONE_REPARTO, 999999, self.in1.pk)
        self.riga(M.PERSONA_MANSIONE, self.rossi, 999999, modo=M.ENTRA, livello="U")
        self.riga(M.PERSONA_RUOLO, self.rossi, 999999, modo="aggiungi")
        ctx = self.ctx(requisiti=False)
        self.assertTrue(all(r["problema"] for r in ctx["righe_modifiche"]))
        self.assertTrue(all(r["delta"] == 0 for r in ctx["kpi"]))

    def test_una_responsabilita_non_si_sposta(self):
        self.riga(M.MANSIONE_REPARTO, self.resp_fres.pk, self.sa1.pk)
        self.assertIn("Responsabilità", self.ctx(requisiti=False)["righe_modifiche"][0]["problema"])


class ApplicaTests(_Base):
    def _applica(self, data=None):
        return svc.applica(self.p, data=data or self.oggi, user=self.admin)

    def test_il_dopo_simulato_e_quello_vero(self):
        """La prova che conta: ciò che il prospetto annuncia è ciò che si trova dopo averlo applicato."""
        self.riga(M.REPARTO_CENTRO, self.in2.pk, self.sal.pk)
        self.riga(M.PERSONA_REPARTO, self.verdi, self.in1.pk, modo=M.LASCIA)
        self.riga(M.PERSONA_MANSIONE, self.rossi, self.m2.pk, modo=M.ENTRA, livello="U")
        self.riga(M.PERSONA_RUOLO, self.neri, self.op.pk, modo="aggiungi")
        self.riga(M.MANSIONE_REPARTO, self.m3.pk, self.in2.pk)
        annunciato = self.ctx(requisiti=False)
        conta = self._applica()
        self.assertEqual(conta.get("errori", 0), 0, [m.esito for m in self.p.modifiche.all()])
        capo_team.invalida_cache()
        vero = svc.Base()
        capi = capo_team.mappa_capi()
        mis = svc.misure(vero, vero.stato, soglia_mansioni=8, soglia_concentrazione=80, capi=capi)
        nuovo_p = P.objects.create(nome="Dopo")
        reale = svc.costruisci(nuovo_p, requisiti=False)
        for r in annunciato["kpi"]:
            self.assertEqual(r["dopo"], next(x["prima"] for x in reale["kpi"] if x["chiave"] == r["chiave"]), r["voce"])
        for r in annunciato["centri"]:
            altra = next(x for x in reale["centri"] if x["voce"] == r["voce"])
            self.assertEqual((r["persone_dopo"], r["rml_dopo"], r["medio_dopo"]), (altra["persone_prima"], altra["rml_prima"], altra["medio_prima"]), r["voce"])
        for mid, dato in mis["per_mansione"].items():
            attesa = next((x for x in annunciato["mansioni"] if x["id"] == mid), None)
            if attesa:
                self.assertEqual((attesa["lista_dopo"], attesa["operativi_dopo"]), (dato["lista"], dato["operativi"]), attesa["voce"])
                self.assertEqual(attesa["fte_dopo"], svc.d_due(dato["fte"]), attesa["voce"])
        for r in annunciato["persone"]:
            attuale = capi.get(r["id"])
            nome = vero.nome_persona(attuale.legacy_id) if attuale and attuale.legacy_id else "nessuno"
            self.assertEqual(r["capo_dopo"], nome, r["nome"])

    def test_spostamento_registrato_e_tracciato(self):
        self.riga(M.PERSONA_REPARTO, self.verdi, self.in1.pk, modo=M.LASCIA)
        self._applica()
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.verdi)
        self.assertEqual(az.area_aziendale, self.in1)
        self.assertTrue(DipendenteAssegnazione.objects.filter(legacy_anagrafica_id=self.verdi, note__contains="Prova").exists())
        self.assertFalse(AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=self.verdi, competenza=self.m2, in_lista=True).exists())
        self.p.refresh_from_db()
        self.assertEqual(self.p.stato, P.STATO_APPLICATO)
        self.assertTrue(self.p.fotografia["kpi"])
        riga = self.p.modifiche.get()
        self.assertTrue(riga.esito_ok)
        self.assertIn("tolte 2 mansioni", riga.esito)

    def test_decorrenza_futura_non_toglie_ancora_niente(self):
        self.riga(M.PERSONA_REPARTO, self.verdi, self.in1.pk, modo=M.LASCIA)
        self._applica(self.oggi + timedelta(days=30))
        self.assertEqual(DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.verdi).area_aziendale, self.sa1)
        self.assertTrue(AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=self.verdi, competenza=self.m2, in_lista=True).exists())
        self.assertIn("alla decorrenza", self.p.modifiche.get().esito)

    def test_una_riga_che_non_riesce_non_ferma_le_altre(self):
        self.riga(M.PERSONA_REPARTO, 999999, self.in1.pk, modo=M.TIENE)
        self.riga(M.REPARTO_CENTRO, self.in2.pk, self.sal.pk)
        conta = self._applica()
        self.assertEqual((conta["errori"], conta["ok"]), (1, 1))
        self.in2.refresh_from_db()
        self.assertEqual(self.in2.centro_di_costo, self.sal)
        self.assertEqual(self.p.modifiche.filter(esito_ok=False).count(), 1)


class PagineTests(_Base):
    def url(self):
        return reverse("anagrafica:prospetto", args=[self.p.pk])

    def test_elenco_nuovo_e_pagina(self):
        r = self.client.get(reverse("anagrafica:prospetti"))
        self.assertContains(r, "Prova")
        self.assertNotContains(r, "{#")
        r = self.client.post(reverse("anagrafica:prospetto_crea"), {"nome": "Sdoppio"}, follow=True)
        self.assertContains(r, "Sdoppio")
        self.assertNotContains(r, "{#")

    def test_aggiungere_in_blocco_e_rifare_sostituisce(self):
        u = reverse("anagrafica:prospetto_aggiungi", args=[self.p.pk])
        self.client.post(u, {"tipo": M.PERSONA_REPARTO, "persone": [self.rossi, self.bianchi], "area": self.sa1.pk, "mansioni": "lascia"})
        self.assertEqual(self.p.modifiche.count(), 2)
        self.client.post(u, {"tipo": M.PERSONA_REPARTO, "persone": [self.rossi], "area": self.in2.pk, "mansioni": "tiene"})
        self.assertEqual(self.p.modifiche.count(), 2)
        self.assertEqual(self.p.modifiche.get(soggetto_id=self.rossi).destinazione_id, self.in2.pk)
        self.assertEqual(self.p.modifiche.get(soggetto_id=self.rossi).modo, "tiene")
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Reparti toccati")
        self.assertContains(r, "Persone toccate")

    def test_tutti_i_tipi_si_aggiungono_e_si_vedono(self):
        u = reverse("anagrafica:prospetto_aggiungi", args=[self.p.pk])
        self.client.post(u, {"tipo": M.REPARTO_CENTRO, "area": self.in1.pk, "centro": ""})
        self.client.post(u, {"tipo": M.MANSIONE_REPARTO, "mansione": self.m1.pk, "area": self.sa1.pk})
        self.client.post(u, {"tipo": M.PERSONA_RUOLO, "persone": [self.rossi], "ruolo": self.capo.pk, "modo": "aggiungi"})
        self.client.post(u, {"tipo": M.PERSONA_MANSIONE, "persone": [self.rossi], "mansione": self.m2.pk, "modo": "entra", "livello": "O"})
        self.assertEqual(self.p.modifiche.count(), 4)
        r = self.client.get(self.url())
        self.assertContains(r, SENZA_CENTRO)
        self.assertNotContains(r, "Non vale")

    def test_dati_mancanti_danno_un_messaggio(self):
        u = reverse("anagrafica:prospetto_aggiungi", args=[self.p.pk])
        for dati in ({"tipo": "BOH"}, {"tipo": M.PERSONA_REPARTO, "area": self.in1.pk}, {"tipo": M.PERSONA_REPARTO, "persone": [self.rossi]},
                     {"tipo": M.REPARTO_CENTRO}, {"tipo": M.PERSONA_RUOLO, "persone": [self.rossi], "ruolo": self.capo.pk, "modo": "boh"}):
            self.client.post(u, dati)
        self.assertEqual(self.p.modifiche.count(), 0)

    def test_soglie_valide_e_no(self):
        u = reverse("anagrafica:prospetto_soglie", args=[self.p.pk])
        self.client.post(u, {"soglia_mansioni": 5, "soglia_concentrazione": 60})
        self.p.refresh_from_db()
        self.assertEqual((self.p.soglia_mansioni_persona, self.p.soglia_concentrazione), (5, 60))
        self.client.post(u, {"soglia_mansioni": 0, "soglia_concentrazione": 500})
        self.p.refresh_from_db()
        self.assertEqual((self.p.soglia_mansioni_persona, self.p.soglia_concentrazione), (5, 60))

    def test_confronto_con_un_altro_prospetto(self):
        altro = P.objects.create(nome="Alternativa")
        M.objects.create(prospetto=altro, tipo=M.REPARTO_CENTRO, soggetto_id=self.in2.pk, destinazione_id=self.sal.pk)
        r = self.client.get(self.url(), {"con": altro.pk})
        self.assertContains(r, "Alternativa")
        riga = next(x for x in r.context["centri"] if x["voce"] == "SALDATURE")
        self.assertEqual((riga["persone_dopo"], riga["persone_altro"]), (2, 3))
        self.assertEqual(self.client.get(self.url(), {"con": "abc"}).status_code, 200)

    def test_applica_chiede_conferma_e_data(self):
        self.riga(M.REPARTO_CENTRO, self.in2.pk, self.sal.pk)
        u = reverse("anagrafica:prospetto_applica", args=[self.p.pk])
        self.client.post(u, {"decorrenza": self.oggi.isoformat()})
        self.client.post(u, {"conferma": "1", "decorrenza": "boh"})
        self.p.refresh_from_db()
        self.assertEqual(self.p.stato, P.STATO_BOZZA)
        r = self.client.post(u, {"conferma": "1", "decorrenza": self.oggi.isoformat()}, follow=True)
        self.assertContains(r, "Il confronto al momento di applicare")
        self.p.refresh_from_db()
        self.assertEqual(self.p.stato, P.STATO_APPLICATO)
        # Chiuso: non si tocca più
        self.client.post(reverse("anagrafica:prospetto_aggiungi", args=[self.p.pk]), {"tipo": M.REPARTO_CENTRO, "area": self.in1.pk})
        self.assertEqual(self.p.modifiche.count(), 1)

    def test_archiviare_non_cambia_niente(self):
        self.riga(M.REPARTO_CENTRO, self.in2.pk, self.sal.pk)
        self.client.post(reverse("anagrafica:prospetto_annulla", args=[self.p.pk]))
        self.p.refresh_from_db()
        self.in2.refresh_from_db()
        self.assertEqual((self.p.stato, self.in2.centro_di_costo), (P.STATO_ANNULLATO, self.lav))

    def test_chi_non_amministra_non_prepara(self):
        utente = User.objects.create_user("pro_user", "u@example.invalid", "x")
        self.client.force_login(utente)
        self.assertIn(self.client.get(self.url()).status_code, (302, 403))
        self.client.post(reverse("anagrafica:prospetto_crea"), {"nome": "Abusivo"})
        self.client.post(reverse("anagrafica:prospetto_aggiungi", args=[self.p.pk]), {"tipo": M.REPARTO_CENTRO, "area": self.in1.pk})
        self.client.post(reverse("anagrafica:prospetto_applica", args=[self.p.pk]), {"conferma": "1", "decorrenza": self.oggi.isoformat()})
        self.p.refresh_from_db()
        self.assertEqual((self.p.stato, self.p.modifiche.count()), (P.STATO_BOZZA, 0))
        self.assertFalse(P.objects.filter(nome="Abusivo").exists())

    def test_senza_permesso_hr_niente_costi(self):
        from unittest.mock import patch

        self.riga(M.REPARTO_CENTRO, self.in2.pk, self.sal.pk)
        with patch("anagrafica.views_prospetto.puo_costi", return_value=False):
            r = self.client.get(self.url())
            self.assertNotContains(r, "RML oggi")
            self.assertNotContains(r, "10.389,60")
            richiesta = self.client.get(self.url(), {"id": self.p.pk}).wsgi_request
            righe = EXPORT_SPECS["prospetto"].dataset(richiesta, "filtered")
        self.assertTrue(righe)
        self.assertFalse(any("RML" in x["sezione"] or "Costo" in x["sezione"] for x in righe))
        r = self.client.get(self.url())
        self.assertContains(r, "RML oggi")

    def test_export(self):
        self.riga(M.REPARTO_CENTRO, self.in2.pk, self.sal.pk)
        for formato in ("xlsx", "pdf"):
            r = self.client.get(reverse("anagrafica:export", args=["prospetto"]), {"format": formato, "scope": "filtered", "id": self.p.pk})
            self.assertEqual(r.status_code, 200, formato)
        richiesta = self.client.get(self.url(), {"id": self.p.pk}).wsgi_request
        righe = EXPORT_SPECS["prospetto"].dataset(richiesta, "filtered")
        sezioni = {x["sezione"] for x in righe}
        self.assertLessEqual({"Cambiamenti provati", "Riepilogo", "Persone per centro di costo", "RML per centro di costo (€)"}, sezioni)

    def test_ingresso_da_esplora(self):
        r = self.client.get(reverse("anagrafica:esplora_struttura"))
        self.assertContains(r, reverse("anagrafica:prospetti"))
