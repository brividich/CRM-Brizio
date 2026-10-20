"""PART 145: legame attrezzature ↔ processi MOD.128, avviso cambio stato, dossier.

Dati sintetici (nomi e codici fittizi, email example.test).
"""
from __future__ import annotations

from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from anagrafica.models_mpq import AbilitazioneProcesso, ClienteQualificante, ProcessoQualificato
from core.models import UserOnboarding

from .models import Asset, WorkOrder
from .services import part145, part145_dossier

User = get_user_model()


def _admin(username="p145.admin"):
    user = User.objects.create_user(username=username, password="x", email=f"{username}@example.test",
                                    is_superuser=True, is_staff=True)
    UserOnboarding.objects.update_or_create(
        user=user, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()})
    return user


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class Part145Tests(TestCase):
    def setUp(self):
        self.admin = _admin()
        self.client.force_login(self.admin)
        cliente = ClienteQualificante.objects.create(nome="Cliente sintetico")
        self.p145 = ProcessoQualificato.objects.create(nome="Manutenzione componenti sintetica", regime="PART145",
                                                       cliente=cliente,
                                                       data_scadenza=timezone.localdate() + timedelta(days=20))
        self.nadcap = ProcessoQualificato.objects.create(nome="Trattamento sintetico", regime="NADCAP", cliente=cliente)
        self.flag = Asset.objects.create(asset_tag="SYN-145-A", name="Banco prova", part_145=True, reparto="CQF",
                                         serial_number="SN-1")
        self.altro = Asset.objects.create(asset_tag="SYN-145-B", name="Forno sintetico", reparto="Forni")

    def test_attrezzature_processo_unisce_flag_e_collegate(self):
        self.altro.processi_qualificati.add(self.nadcap)
        self.assertEqual(list(part145.attrezzature_processo(self.p145)), [self.flag])
        self.assertEqual(list(part145.attrezzature_processo(self.nadcap)), [self.altro])
        self.assertEqual(part145.processi_dell_asset(self.flag), [self.p145])

    def test_collega_e_scollega_dal_dettaglio_mod128(self):
        url = reverse("anagrafica:mpq_attrezzatura_add", args=[self.nadcap.pk])
        self.client.post(url, {"asset": "syn-145-b"})
        self.assertTrue(self.altro.processi_qualificati.filter(pk=self.nadcap.pk).exists())
        dettaglio = self.client.get(reverse("anagrafica:mpq_processo_detail", args=[self.nadcap.pk]))
        self.assertContains(dettaglio, "SYN-145-B")
        self.assertContains(dettaglio, "Collegata qui")
        self.client.post(reverse("anagrafica:mpq_attrezzatura_remove", args=[self.nadcap.pk, self.altro.pk]))
        self.assertFalse(self.altro.processi_qualificati.exists())
        # Tag inesistente: nessun collegamento, messaggio d'errore.
        risposta = self.client.post(url, {"asset": "NON-ESISTE"}, follow=True)
        self.assertContains(risposta, "Nessun asset")

    def test_collegare_richiede_gestione_mod128(self):
        utente = User.objects.create_user(username="p145.base", password="x")
        UserOnboarding.objects.update_or_create(
            user=utente, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()})
        self.client.force_login(utente)
        with patch("anagrafica.views_mpq._check_mpq_permission", return_value=False):
            self.client.post(reverse("anagrafica:mpq_attrezzatura_add", args=[self.nadcap.pk]), {"asset": "SYN-145-B"})
        self.assertFalse(self.altro.processi_qualificati.exists())

    def test_scheda_asset_mostra_i_processi(self):
        risposta = self.client.get(reverse("assets:asset_view", args=[self.flag.pk]))
        self.assertContains(risposta, reverse("anagrafica:mpq_processo_detail", args=[self.p145.pk]))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_avviso_cambio_stato_solo_attrezzature_qualificate(self):
        with patch("anagrafica.services.reminders.get_reminder_recipients", return_value=["qualita@example.test"]):
            with self.captureOnCommitCallbacks(execute=True):
                self.flag.status = Asset.STATUS_IN_REPAIR
                self.flag.save()
                self.altro.status = Asset.STATUS_IN_REPAIR
                self.altro.save()
        self.assertEqual(len(mail.outbox), 1)
        corpo = mail.outbox[0].alternatives[0][0] if mail.outbox[0].alternatives else mail.outbox[0].body
        self.assertIn("SYN-145-A", corpo)
        self.assertNotIn("SYN-145-B", corpo)
        # Salvataggio senza cambio di stato: nessuna mail.
        mail.outbox.clear()
        with patch("anagrafica.services.reminders.get_reminder_recipients", return_value=["qualita@example.test"]):
            with self.captureOnCommitCallbacks(execute=True):
                self.flag.name = "Banco prova 2"
                self.flag.save()
        self.assertEqual(len(mail.outbox), 0)

    def test_dossier_sezioni_e_situazioni_aperte(self):
        AbilitazioneProcesso.objects.create(legacy_anagrafica_id=990001, processo=self.p145, is_part145=True)
        WorkOrder.objects.create(asset=self.flag, title="Controllo sintetico", kind="CORRECTIVE")
        Asset.objects.filter(pk=self.flag.pk).update(status=Asset.STATUS_IN_REPAIR)
        dati = part145_dossier.costruisci()
        sezioni = {s.codice: s for s in dati["sezioni"]}
        self.assertEqual([r[0] for r in sezioni["attrezzature"].righe], ["SYN-145-A"])
        self.assertEqual(len(sezioni["personale"].righe), 1)
        self.assertEqual(sezioni["scadenze"].righe[0][1], "Processo")
        tipi = {r[0] for r in sezioni["aperte"].righe}
        self.assertIn("Attrezzatura in riparazione", tipi)
        self.assertIn("OdL aperto (Correttiva)", tipi)
        senza = part145_dossier.costruisci(con_personale=False)
        self.assertNotIn("personale", {s.codice for s in senza["sezioni"]})

    def test_situazioni_aperte_hanno_dove_si_risolve(self):
        wo = WorkOrder.objects.create(asset=self.flag, title="Controllo sintetico", kind="CORRECTIVE")
        Asset.objects.filter(pk=self.flag.pk).update(status=Asset.STATUS_IN_REPAIR)
        aperte = {s.codice: s for s in part145_dossier.costruisci()["sezioni"]}["aperte"]
        azioni = {riga[0]: azione for riga, _, azione in aperte.righe_link}
        self.assertEqual(azioni["Attrezzatura in riparazione"][1], reverse("assets:asset_view", args=[self.flag.pk]))
        self.assertEqual(azioni["OdL aperto (Correttiva)"][1], reverse("assets:wo_view", args=[wo.pk]))
        self.assertEqual(azioni["Processo senza persone abilitate"][1],
                         reverse("anagrafica:mpq_processo_detail", args=[self.p145.pk]))
        # Senza permesso MOD.128 niente link verso MOD.128.
        processi = {s.codice: s for s in part145_dossier.costruisci(con_personale=False)["sezioni"]}["processi"]
        self.assertFalse(processi.ha_azioni)
        pagina = self.client.get(reverse("assets:part_145_list"))
        self.assertContains(pagina, "Cosa fare")
        self.assertContains(pagina, reverse("assets:wo_view", args=[wo.pk]))
        dettaglio = self.client.get(reverse("anagrafica:mpq_processo_detail", args=[self.p145.pk]))
        self.assertContains(dettaglio, "Dossier PART 145")

    def test_pagina_ed_export_del_dossier(self):
        pagina = self.client.get(reverse("assets:part_145_list"))
        self.assertContains(pagina, "Dossier PART 145")
        self.assertContains(pagina, "Banco prova")
        xlsx = self.client.get(reverse("assets:part_145_export_excel"))
        wb = load_workbook(BytesIO(xlsx.content))
        self.assertIn("Riepilogo", wb.sheetnames)
        self.assertIn("Attrezzature", wb.sheetnames)
        pdf = self.client.get(reverse("assets:part_145_export_pdf"))
        self.assertTrue(pdf.content.startswith(b"%PDF"))

    def test_dossier_nascosto_il_personale_senza_permesso_mod128(self):
        with patch("assets.services.part145_dossier.puo_vedere_personale", return_value=False):
            pagina = self.client.get(reverse("assets:part_145_list"))
        self.assertContains(pagina, "servono i permessi sui processi qualificati")
        self.assertNotIn("personale", {s.codice for s in pagina.context["dossier"]["sezioni"]})
