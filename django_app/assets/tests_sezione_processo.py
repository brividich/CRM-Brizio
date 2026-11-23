"""Sezioni dedicate dei processi qualificati (MOD.128): spunta, menu, pagine Asset e Qualifiche, export.

Dati sintetici (nomi e codici fittizi, email example.test).
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import SubnavLinkAnagrafica
from anagrafica.models_mpq import (
    AbilitazioneProcesso,
    ClienteQualificante,
    ProcessoQualificato,
    QualificaMacchina,
    RegistroUtensile,
    TechnicalPlan,
    TechnicalPlanPasso,
    TechnicalPlanRevisione,
    UtensileCritico,
)
from core.models import UserOnboarding

from .models import Asset, AssetSidebarButton
from .services import sezione_processo

User = get_user_model()


def _utente(username, **extra):
    user = User.objects.create_user(username=username, password="x", email=f"{username}@example.test", **extra)
    UserOnboarding.objects.update_or_create(
        user=user, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()})
    return user


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SezioneProcessoTests(TestCase):
    def setUp(self):
        self.admin = _utente("p11.admin", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)
        self.cliente = ClienteQualificante.objects.create(nome="Cliente sintetico")
        self.processo = ProcessoQualificato.objects.create(
            nome="Foratura sintetica", cliente=self.cliente, sezione_dedicata=True, sezione_sigla="P11TF12",
            sezione_titolo="Foratura su particolari critici", frequenza_macchine_mesi=12)
        self.altro = ProcessoQualificato.objects.create(nome="Trattamento sintetico", cliente=self.cliente)
        self.macchina = Asset.objects.create(asset_tag="SYN-P11-A", name="Foratrice sintetica", reparto="CNC")
        self.macchina.processi_qualificati.add(self.processo)
        QualificaMacchina.objects.create(processo=self.processo, asset=self.macchina,
                                         stato=QualificaMacchina.STATO_DA_VALUTARE)
        self.utensile = UtensileCritico.objects.create(processo=self.processo, codice="UT-SYN-1",
                                                       descrizione="Punta sintetica", fornitore="Fornitore sintetico")
        self.tp = TechnicalPlan.objects.create(processo=self.processo, part_number="PN-SYN-1", tipologia_foro="Foro A")
        rev = TechnicalPlanRevisione.objects.create(plan=self.tp, numero=1, modifiche="Prima emissione",
                                                    stato=TechnicalPlanRevisione.STATO_APPROVATA,
                                                    approvato_da="Agente sintetico",
                                                    data_approvazione=timezone.localdate() - timedelta(days=10))
        passo = TechnicalPlanPasso.objects.create(revisione=rev, utensile=self.utensile, tcp_limite=100)
        self.registro = RegistroUtensile.objects.create(passo=passo, identificativo="KIT-SYN-1",
                                                        stato=RegistroUtensile.STATO_TCP)
        self.tp_bozza = TechnicalPlan.objects.create(processo=self.processo, part_number="PN-SYN-2", tipologia_foro="Foro B")
        TechnicalPlanRevisione.objects.create(plan=self.tp_bozza, numero=1, modifiche="Bozza")

    def test_sezioni_e_da_sistemare(self):
        AbilitazioneProcesso.objects.create(legacy_anagrafica_id=990101, processo=self.processo)
        dati = sezione_processo.costruisci("P11TF12")
        self.assertEqual(dati["titolo"], "P11TF12 – Foratura su particolari critici")
        sezioni = {s.codice: s for s in dati["sezioni"]}
        self.assertEqual([r[0] for r in sezioni["macchine"].righe], ["SYN-P11-A"])
        self.assertEqual(sezioni["macchine"].righe[0][3], "Da valutare")
        self.assertEqual([r[0] for r in sezioni["utensili"].righe], ["UT-SYN-1"])
        self.assertEqual({r[0]: r[2] for r in sezioni["technical_plan"].righe},
                         {"PN-SYN-1": "Rev. 1", "PN-SYN-2": "Nessuna revisione approvata"})
        self.assertEqual([r[0] for r in sezioni["registro"].righe], ["KIT-SYN-1"])
        self.assertEqual(len(sezioni["personale"].righe), 1)
        self.assertEqual(sezioni["documenti"].righe[0][0], "MOD.128")
        tipi = {r[1] for r in sezioni["aperte"].righe}
        self.assertTrue({"Macchina da valutare", "Utensile al TCP",
                         "Technical Plan senza revisione approvata"} <= tipi)
        self.assertEqual(sezioni["aperte"].righe[0][0], "Alta")
        # Ordine delle sezioni: Asset parte dalle macchine, Qualifiche dalle persone.
        self.assertEqual([s.codice for s in dati["sezioni"]][2], "macchine")
        qualifiche = sezione_processo.costruisci("P11TF12", ordine=sezione_processo.ORDINE_QUALIFICHE)
        self.assertEqual([s.codice for s in qualifiche["sezioni"]][2], "personale")

    def test_mostra_solo_le_parti_usate(self):
        ProcessoQualificato.objects.filter(pk=self.altro.pk).update(sezione_dedicata=True, sezione_sigla="TS-01")
        dati = sezione_processo.costruisci("TS-01")
        codici = [s.codice for s in dati["sezioni"]]
        for assente in ("macchine", "utensili", "technical_plan", "registro"):
            self.assertNotIn(assente, codici)
        self.assertIn("personale", codici)
        self.assertNotIn("Macchine", [k["etichetta"] for k in dati["kpi"]])
        self.assertNotIn("Processo senza macchine", {r[1] for r in dati["sezioni"][0].righe})

    def test_senza_permesso_mod128_niente_persone_ne_link(self):
        dati = sezione_processo.costruisci("P11TF12", con_personale=False)
        codici = {s.codice for s in dati["sezioni"]}
        self.assertNotIn("personale", codici)
        self.assertNotIn("formazione", codici)
        self.assertFalse({s.codice: s for s in dati["sezioni"]}["technical_plan"].ha_azioni)

    def test_pagina_asset_ed_export(self):
        url = reverse("assets:processo_sezione", args=["P11TF12"])
        pagina = self.client.get(url)
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, "P11TF12 – Foratura su particolari critici")
        self.assertContains(pagina, "SYN-P11-A")
        self.assertContains(pagina, reverse("anagrafica:mpq_sezione", args=["P11TF12"]))
        self.assertContains(pagina, reverse("assets:processo_sezione_export", args=["P11TF12", "pdf"]))
        self.assertEqual(self.client.get(reverse("assets:processo_sezione", args=["p11tf12"])).status_code, 200)
        pdf = self.client.get(reverse("assets:processo_sezione_export", args=["P11TF12", "pdf"]))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        xlsx = self.client.get(reverse("assets:processo_sezione_export", args=["P11TF12", "xlsx"]))
        self.assertIn("sezione-p11tf12-", xlsx["Content-Disposition"])
        csv = self.client.get(reverse("assets:processo_sezione_export", args=["P11TF12", "csv"]))
        self.assertEqual(csv.status_code, 404)
        self.assertEqual(self.client.get(reverse("assets:processo_sezione", args=["NESSUNA"])).status_code, 404)
        with patch("assets.services.part145_dossier.puo_vedere_personale", return_value=False):
            ridotta = self.client.get(url)
        self.assertContains(ridotta, "servono i permessi sui processi qualificati")
        self.assertNotContains(ridotta, reverse("anagrafica:mpq_sezione", args=["P11TF12"]))
        ProcessoQualificato.objects.filter(pk=self.processo.pk).update(sezione_dove=ProcessoQualificato.DOVE_QUALIFICHE)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_pagina_qualifiche_export_e_permesso(self):
        url = reverse("anagrafica:mpq_sezione", args=["P11TF12"])
        pagina = self.client.get(url)
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, "Personale abilitato")
        self.assertContains(pagina, reverse("assets:processo_sezione", args=["P11TF12"]))
        self.assertContains(pagina, reverse("anagrafica:mpq_processo_detail", args=[self.processo.pk]))
        xlsx = self.client.get(reverse("anagrafica:mpq_sezione_export", args=["P11TF12", "xlsx"]))
        self.assertEqual(xlsx.status_code, 200)
        self.assertTrue(xlsx.content.startswith(b"PK"))
        ProcessoQualificato.objects.filter(pk=self.processo.pk).update(sezione_dove=ProcessoQualificato.DOVE_ASSET)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(_utente("p11.base"))
        with patch("anagrafica.views_mpq._check_mpq_permission", return_value=False):
            negata = self.client.get(url)
        self.assertEqual(negata.status_code, 302)

    def test_vecchi_indirizzi_p11tf12_rimandano_alla_sezione(self):
        self.assertRedirects(self.client.get(reverse("assets:p11tf12")),
                             reverse("assets:processo_sezione", args=["P11TF12"]))
        self.assertRedirects(self.client.get(reverse("anagrafica:mpq_p11tf12")),
                             reverse("anagrafica:mpq_sezione", args=["P11TF12"]))

    def test_dettaglio_processo_e_cruscotto_portano_alla_sezione(self):
        dettaglio = self.client.get(reverse("anagrafica:mpq_processo_detail", args=[self.processo.pk]))
        self.assertContains(dettaglio, reverse("assets:processo_sezione", args=["P11TF12"]))
        altro = self.client.get(reverse("anagrafica:mpq_processo_detail", args=[self.altro.pk]))
        self.assertNotContains(altro, "Sezione dedicata P11TF12")
        cruscotto = self.client.get(reverse("anagrafica:mpq_cruscotto"))
        self.assertContains(cruscotto, reverse("anagrafica:mpq_sezione", args=["P11TF12"]))

    def test_spunta_dal_form_crea_e_toglie_le_voci_di_menu(self):
        dati = {"cliente": self.cliente.pk, "nome": "Trattamento sintetico",
                "regime": ProcessoQualificato.REGIME_SPECIALE,
                "tipo_validita": ProcessoQualificato.VALIDITA_ILLIMITATA,
                "personale_modalita": ProcessoQualificato.MODALITA_NOMINALE,
                "stato": ProcessoQualificato.STATO_ATTIVO,
                "sezione_dedicata": "on", "sezione_sigla": "ts 02", "sezione_titolo": "Trattamento sintetico",
                "sezione_dove": ProcessoQualificato.DOVE_ENTRAMBE}
        modifica = reverse("anagrafica:mpq_processo_edit", args=[self.altro.pk])
        sbagliata = self.client.post(modifica, {**dati, "sezione_sigla": "T"})
        self.assertEqual(sbagliata.status_code, 200)
        self.assertContains(sbagliata, "Da 2 a 30 caratteri")
        risposta = self.client.post(modifica, dati)
        self.assertEqual(risposta.status_code, 302)
        self.altro.refresh_from_db()
        self.assertEqual(self.altro.sezione_sigla, "TS02")
        url_menu = reverse("anagrafica:mpq_sezione", args=["TS02"])
        voce = SubnavLinkAnagrafica.objects.get(url_value=url_menu)
        self.assertEqual(voce.etichetta, "TS02 – Trattamento sintetico")
        self.assertTrue(AssetSidebarButton.objects.filter(code="sezione-ts02", label="TS02").exists())
        self.assertEqual(self.client.get(url_menu).status_code, 200)
        # Solo Qualifiche: la voce Asset sparisce, quella di Qualifiche resta.
        self.client.post(modifica, {**dati, "sezione_dove": ProcessoQualificato.DOVE_QUALIFICHE})
        self.assertFalse(AssetSidebarButton.objects.filter(code="sezione-ts02").exists())
        self.assertTrue(SubnavLinkAnagrafica.objects.filter(url_value=url_menu).exists())
        # Senza spunta spariscono le voci, i dati restano.
        self.client.post(modifica, {k: v for k, v in dati.items() if k != "sezione_dedicata"})
        self.assertFalse(SubnavLinkAnagrafica.objects.filter(url_value=url_menu).exists())
        self.assertTrue(ProcessoQualificato.objects.filter(pk=self.altro.pk, sezione_sigla="TS02").exists())

    def test_stessa_sigla_su_due_processi_una_sola_pagina_e_voce(self):
        from anagrafica.services.mpq_sezioni import sincronizza_menu

        ProcessoQualificato.objects.filter(pk=self.altro.pk).update(sezione_dedicata=True, sezione_sigla="P11TF12")
        sincronizza_menu()
        sincronizza_menu()
        dati = sezione_processo.costruisci("P11TF12")
        self.assertEqual(len(dati["processi"]), 2)
        self.assertEqual(SubnavLinkAnagrafica.objects.filter(
            url_value=reverse("anagrafica:mpq_sezione", args=["P11TF12"])).count(), 1)
        self.assertEqual(AssetSidebarButton.objects.filter(code="sezione-p11tf12").count(), 1)

    def test_ricerca_globale_trova_sezione_e_processi(self):
        risposta = self.client.get(reverse("api_global_search"), {"q": "p11tf"})
        processi = [r for r in risposta.json()["results"] if r["tipo"] == "processo"]
        self.assertEqual([r["url"] for r in processi], [reverse("anagrafica:mpq_sezione", args=["P11TF12"])])
        self.assertEqual(processi[0]["label"], "P11TF12 – Foratura su particolari critici")
        self.assertEqual(processi[0]["module"], "Processi qualificati")
        altro = self.client.get(reverse("api_global_search"), {"q": "trattamento sint"}).json()["results"]
        self.assertIn(reverse("anagrafica:mpq_processo_detail", args=[self.altro.pk]),
                      [r["url"] for r in altro if r["tipo"] == "processo"])
        # Solo Asset: porta alla pagina Asset.
        ProcessoQualificato.objects.filter(pk=self.processo.pk).update(sezione_dove=ProcessoQualificato.DOVE_ASSET)
        asset = self.client.get(reverse("api_global_search"), {"q": "p11tf"}).json()["results"]
        self.assertEqual([r["url"] for r in asset if r["tipo"] == "processo"],
                         [reverse("assets:processo_sezione", args=["P11TF12"])])

    def test_ricerca_globale_senza_permesso_mod128_niente_processi(self):
        self.client.force_login(_utente("p11.nessuno"))
        with patch("anagrafica.views_mpq._check_mpq_permission", return_value=False), \
             patch("core.views._global_search_module_allowed", return_value=True):
            risultati = self.client.get(reverse("api_global_search"), {"q": "p11tf"}).json()["results"]
        self.assertFalse([r for r in risultati if r["tipo"] == "processo"])

    def test_pagina_qualifiche_ha_la_ricerca_su_tutte_le_sezioni(self):
        pagina = self.client.get(reverse("anagrafica:mpq_sezione", args=["P11TF12"]))
        self.assertContains(pagina, 'id="p11-cerca"')
        self.assertContains(pagina, 'data-fm-hide-search="1"')

    def test_cambio_titolo_rinomina_la_voce_ma_non_quella_rinominata_a_mano(self):
        from anagrafica.services.mpq_sezioni import sincronizza_menu

        sincronizza_menu()
        url_menu = reverse("anagrafica:mpq_sezione", args=["P11TF12"])
        ProcessoQualificato.objects.filter(pk=self.processo.pk).update(sezione_titolo="Foratura nuova")
        sincronizza_menu()
        self.assertEqual(SubnavLinkAnagrafica.objects.get(url_value=url_menu).etichetta, "P11TF12 – Foratura nuova")
        SubnavLinkAnagrafica.objects.filter(url_value=url_menu).update(etichetta="Fori critici")
        ProcessoQualificato.objects.filter(pk=self.processo.pk).update(sezione_titolo="Altro titolo")
        sincronizza_menu()
        self.assertEqual(SubnavLinkAnagrafica.objects.get(url_value=url_menu).etichetta, "Fori critici")

    def test_scarica_solo_le_righe_trovate(self):
        dati = sezione_processo.costruisci("P11TF12")
        estratto = sezione_processo.filtra(dati, "pn-syn-2")
        self.assertEqual([s.codice for s in estratto["sezioni"]], ["aperte", "technical_plan"])
        tp = next(s for s in estratto["sezioni"] if s.codice == "technical_plan")
        self.assertEqual([r[0] for r in tp.righe], ["PN-SYN-2"])
        self.assertEqual(len(tp.azioni), 1)
        self.assertIn("«pn-syn-2»", estratto["titolo_export"])
        self.assertTrue(estratto["nome_file"].endswith("-estratto"))
        self.assertIs(sezione_processo.filtra(dati, "  "), dati)
        # Le sezioni originali non cambiano.
        self.assertEqual(len(next(s for s in dati["sezioni"] if s.codice == "technical_plan").righe), 2)
        macc = sezione_processo.filtra(dati, "foratrice")
        m = next(s for s in macc["sezioni"] if s.codice == "macchine")
        self.assertEqual(m.asset_ids, [self.macchina.pk])
        for url in (reverse("assets:processo_sezione_export", args=["P11TF12", "xlsx"]),
                    reverse("anagrafica:mpq_sezione_export", args=["P11TF12", "xlsx"])):
            r = self.client.get(url, {"q": "PN-SYN-2"})
            self.assertEqual(r.status_code, 200)
            self.assertIn("-estratto.xlsx", r["Content-Disposition"])
        pagina = self.client.get(reverse("anagrafica:mpq_sezione", args=["P11TF12"]))
        self.assertContains(pagina, "hidden data-solo-trovate", count=2)
        asset = self.client.get(reverse("assets:processo_sezione", args=["P11TF12"]))
        self.assertContains(asset, "hidden data-solo-trovate", count=2)

    def test_scadenze_vicine_evidenziate(self):
        oggi = timezone.localdate()
        ProcessoQualificato.objects.filter(pk=self.processo.pk).update(
            tipo_validita=ProcessoQualificato.VALIDITA_DATA, data_scadenza=oggi + timedelta(days=10))
        dati = sezione_processo.costruisci("P11TF12")
        kpi = next(k for k in dati["kpi"] if k["sezione"] == "scadenze")
        self.assertIn("entro 30 giorni", kpi["nota"])
        pagina = self.client.get(reverse("anagrafica:mpq_sezione", args=["P11TF12"]))
        self.assertContains(pagina, 'class="p11-r-warn"')
        asset = self.client.get(reverse("assets:processo_sezione", args=["P11TF12"]))
        self.assertContains(asset, 'class="p145-r-warn"')

    def test_cruscotto_mostra_la_sigla_e_avviso_riferimenti_mancanti(self):
        cruscotto = self.client.get(reverse("anagrafica:mpq_cruscotto"))
        self.assertContains(cruscotto, 'title="Apri la sezione dedicata">P11TF12</a>')
        dettaglio = self.client.get(reverse("anagrafica:mpq_processo_detail", args=[self.processo.pk]))
        self.assertContains(dettaglio, "mpq-avviso-rif")
        self.processo.riferimenti.create(codice="MOD.161")
        dettaglio = self.client.get(reverse("anagrafica:mpq_processo_detail", args=[self.processo.pk]))
        self.assertNotContains(dettaglio, "mpq-avviso-rif")

    def test_mail_scadenze_porta_alla_sezione(self):
        from anagrafica.services.mpq_scadenze import _processo_html

        self.assertIn(reverse("anagrafica:mpq_sezione", args=["P11TF12"]), _processo_html(self.processo))
        self.assertEqual(_processo_html(self.altro), "Trattamento sintetico")
