"""Pagine P11TF12 (Asset e Qualifiche): foratura su particolari critici dai dati MOD.128.

Dati sintetici (nomi e codici fittizi, email example.test).
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models_mpq import (
    AbilitazioneProcesso,
    ClienteQualificante,
    ProcessoQualificato,
    QualificaMacchina,
    RegistroUtensile,
    RiferimentoProcesso,
    TechnicalPlan,
    TechnicalPlanPasso,
    TechnicalPlanRevisione,
    UtensileCritico,
)
from core.models import UserOnboarding

from .models import Asset, AssetSidebarButton
from .services import p11tf12_dossier

User = get_user_model()


def _utente(username, **extra):
    user = User.objects.create_user(username=username, password="x", email=f"{username}@example.test", **extra)
    UserOnboarding.objects.update_or_create(
        user=user, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()})
    return user


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class P11tf12Tests(TestCase):
    def setUp(self):
        self.admin = _utente("p11.admin", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)
        cliente = ClienteQualificante.objects.create(nome="Cliente sintetico")
        self.processo = ProcessoQualificato.objects.create(nome="P11TF12 – Foratura sintetica", cliente=cliente)
        self.altro = ProcessoQualificato.objects.create(nome="Trattamento sintetico", cliente=cliente)
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

    def test_riconosce_il_processo_dal_nome_o_dai_riferimenti(self):
        self.assertEqual(list(p11tf12_dossier.processi()), [self.processo])
        self.assertTrue(p11tf12_dossier.e_p11tf12(self.processo))
        self.assertFalse(p11tf12_dossier.e_p11tf12(self.altro))
        RiferimentoProcesso.objects.create(processo=self.altro, codice="MT CN 69 – P11TF12")
        self.assertTrue(p11tf12_dossier.e_p11tf12(self.altro))
        self.assertEqual(set(p11tf12_dossier.processi()), {self.processo, self.altro})

    def test_sezioni_e_da_sistemare(self):
        AbilitazioneProcesso.objects.create(legacy_anagrafica_id=990101, processo=self.processo)
        dati = p11tf12_dossier.costruisci()
        sezioni = {s.codice: s for s in dati["sezioni"]}
        self.assertEqual([r[0] for r in sezioni["macchine"].righe], ["SYN-P11-A"])
        self.assertEqual(sezioni["macchine"].righe[0][3], "Da valutare")
        self.assertEqual([r[0] for r in sezioni["utensili"].righe], ["UT-SYN-1"])
        self.assertEqual({r[0]: r[2] for r in sezioni["technical_plan"].righe},
                         {"PN-SYN-1": "Rev. 1", "PN-SYN-2": "Nessuna revisione approvata"})
        self.assertEqual([r[0] for r in sezioni["registro"].righe], ["KIT-SYN-1"])
        self.assertEqual(len(sezioni["personale"].righe), 1)
        tipi = {r[1] for r in sezioni["aperte"].righe}
        self.assertTrue({"Macchina da valutare", "Utensile al TCP",
                         "Technical Plan senza revisione approvata"} <= tipi)
        self.assertEqual(sezioni["aperte"].righe[0][0], "Alta")
        # Ordine delle sezioni: Asset parte dalle macchine, Qualifiche dalle persone.
        self.assertEqual([s.codice for s in dati["sezioni"]][2], "macchine")
        qualifiche = p11tf12_dossier.costruisci(ordine=p11tf12_dossier.ORDINE_QUALIFICHE)
        self.assertEqual([s.codice for s in qualifiche["sezioni"]][2], "personale")

    def test_senza_permesso_mod128_niente_persone_ne_link(self):
        dati = p11tf12_dossier.costruisci(con_personale=False)
        codici = {s.codice for s in dati["sezioni"]}
        self.assertNotIn("personale", codici)
        self.assertNotIn("formazione", codici)
        self.assertFalse({s.codice: s for s in dati["sezioni"]}["technical_plan"].ha_azioni)

    def test_nessun_processo_dice_come_crearlo(self):
        ProcessoQualificato.objects.filter(pk=self.processo.pk).update(nome="Foratura senza codice")
        aperte = {s.codice: s for s in p11tf12_dossier.costruisci()["sezioni"]}["aperte"]
        self.assertEqual(aperte.righe[0][1], "Processo da creare")

    def test_pagina_asset(self):
        pagina = self.client.get(reverse("assets:p11tf12"))
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, "P11TF12 – Foratura su particolari critici")
        self.assertContains(pagina, "SYN-P11-A")
        self.assertContains(pagina, reverse("anagrafica:mpq_p11tf12"))
        self.assertContains(pagina, reverse("assets:guida") + "#p11tf12")
        with patch("assets.services.part145_dossier.puo_vedere_personale", return_value=False):
            ridotta = self.client.get(reverse("assets:p11tf12"))
        self.assertContains(ridotta, "servono i permessi sui processi qualificati")
        self.assertNotContains(ridotta, reverse("anagrafica:mpq_p11tf12"))

    def test_pagina_qualifiche_e_permesso(self):
        pagina = self.client.get(reverse("anagrafica:mpq_p11tf12"))
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, "Personale abilitato")
        self.assertContains(pagina, reverse("assets:p11tf12"))
        self.assertContains(pagina, reverse("anagrafica:mpq_processo_detail", args=[self.processo.pk]))
        self.client.force_login(_utente("p11.base"))
        with patch("anagrafica.views_mpq._check_mpq_permission", return_value=False):
            negata = self.client.get(reverse("anagrafica:mpq_p11tf12"))
        self.assertEqual(negata.status_code, 302)

    def test_dettaglio_processo_e_cruscotto_portano_alle_pagine(self):
        dettaglio = self.client.get(reverse("anagrafica:mpq_processo_detail", args=[self.processo.pk]))
        self.assertContains(dettaglio, reverse("assets:p11tf12"))
        altro = self.client.get(reverse("anagrafica:mpq_processo_detail", args=[self.altro.pk]))
        self.assertNotContains(altro, reverse("assets:p11tf12"))
        cruscotto = self.client.get(reverse("anagrafica:mpq_cruscotto"))
        self.assertContains(cruscotto, reverse("anagrafica:mpq_p11tf12"))

    def test_voci_di_menu(self):
        self.assertTrue(AssetSidebarButton.objects.filter(code="p11tf12", target_url="django:assets:p11tf12").exists())
        from anagrafica.models import SubnavLinkAnagrafica

        self.assertTrue(SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:mpq_p11tf12").exists())
