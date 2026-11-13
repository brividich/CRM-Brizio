"""Automatismi del SOC: aggiornamenti KB WatchGuard, doppioni software con l'AI, manutenzione notturna,
andamento della postura, ricerca estesa, eventi con alert. Dati sintetici."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import DispositivoIntune
from core.models import UserOnboarding
from security.models import (
    ParseStatus,
    PosturaGiorno,
    SecurityAlert,
    SecurityAsset,
    SecurityEventRecord,
    SecurityMailboxMessage,
    SecurityPropostaAi,
    SecuritySource,
    SoftwareAlias,
    SoftwareInstallation,
    SourceType,
    WatchGuardAggiornamento,
)
from security.services import manutenzione_soc, software_doppioni, watchguard_api


def _sw(host, vendor, product, version, fonte, raw=None):
    return SoftwareInstallation.objects.create(
        dedup_key=f"{host}|{vendor}|{product}|{version}|{fonte}"[:64], source_kind=fonte, host=host, host_display=host.upper(),
        vendor=vendor, vendor_raw=vendor.title(), product=product, product_raw=raw or product.title(), version_raw=version,
        fonti=[fonte], still_detected=True)


class _Login(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="auto_soc", is_staff=True, is_superuser=True)
        UserOnboarding.objects.create(user=self.user, completed=True)
        self.client.force_login(self.user)


class AggiornamentiKbTests(TestCase):
    def test_kb_salvati_per_pc_e_scarti_contati(self):
        righe = [
            {"host_name": "PC-KB-01", "name": "Acme Viewer", "publisher": "Acme", "version": "1.0"},
            {"host_name": "PC-KB-01", "name": "Aggiornamento cumulativo KB5046633", "publisher": "Microsoft", "version": "1", "is_patch": True,
             "installation_date": "2026-11-01"},
            {"host_name": "PC-KB-01", "name": "", "publisher": "x", "version": "1"},
        ]
        WatchGuardAggiornamento.objects.create(host="pc-kb-01", nome="Vecchio KB")
        with mock.patch("security.services.defender_software._dopo_import"):
            esito = watchguard_api.sincronizza_software(righe=righe)
        self.assertEqual((esito["aggiornamenti_kb"], esito["scartate_aggiornamenti"], esito["scartate_altro"]), (1, 1, 1))
        self.assertEqual(list(WatchGuardAggiornamento.objects.values_list("host", "nome")), [("pc-kb-01", "Aggiornamento cumulativo KB5046633")])


class DoppioniTests(TestCase):
    def setUp(self):
        self.wg = _sw("pc-dp-01", "microsoft", "microsoft onedrive", "25.1", "watchguard", "Microsoft OneDrive")
        self.df = _sw("pc-dp-01", "microsoft", "onedrive", "25.1", "defender", "onedrive")

    def _giro(self, candidati, risposta=None):
        with mock.patch.object(software_doppioni, "candidati", return_value=candidati), \
                mock.patch("security.services.software_inventory.unisci_per_equivalenza", return_value={"fuse": 0}), \
                mock.patch.object(software_doppioni, "_chiedi_ai", return_value=risposta or (None, "AI spenta", "")), \
                mock.patch("security.views_vuln._queue_recompute"):
            return software_doppioni.giro()

    def test_stesso_nome_e_versioni_uguali_si_unisce_da_solo_e_si_annulla(self):
        esito = self._giro([(("microsoft", "onedrive"), ("microsoft", "microsoft onedrive"), 1.0)])
        self.assertEqual(esito["alias_automatici"], 1)
        self.assertTrue(SoftwareAlias.objects.filter(raw="onedrive", canonical="microsoft onedrive").exists())
        righe = SoftwareInstallation.objects.filter(host="pc-dp-01", still_detected=True)
        self.assertEqual(righe.count(), 1)
        self.assertEqual(sorted(righe.first().fonti), ["defender", "watchguard"])
        proposta = SecurityPropostaAi.objects.get(tipo=SecurityPropostaAi.TIPO_DOPPIONE)
        self.assertEqual(proposta.stato, SecurityPropostaAi.ACCETTATA)
        software_doppioni.annulla(proposta)
        self.assertFalse(SoftwareAlias.objects.filter(raw="onedrive").exists())

    def test_ai_sicura_unisce_ai_incerta_lascia_da_decidere(self):
        coppia = [(("microsoft", "onedrive"), ("microsoft", "microsoft onedrive"), 0.85)]
        esito = self._giro(coppia, ({"stesso": True, "confidenza": 70, "motivazione": "probabile"}, "", "llama"))
        self.assertEqual((esito["da_decidere"], esito["alias_ai"]), (1, 0))
        self.assertEqual(len(software_doppioni.da_decidere()), 1)
        SecurityPropostaAi.objects.all().delete()
        esito = self._giro(coppia, ({"stesso": True, "confidenza": 95, "motivazione": "stesso"}, "", "llama"))
        self.assertEqual(esito["alias_ai"], 1)

    def test_ai_dice_diversi_non_unisce_e_non_richiede(self):
        coppia = [(("microsoft", "onedrive"), ("microsoft", "microsoft onedrive"), 0.85)]
        self.assertEqual(self._giro(coppia, ({"stesso": False, "confidenza": 90, "motivazione": "diversi"}, "", "m"))["non_stesso"], 1)
        self.assertEqual(self._giro(coppia, ({"stesso": True, "confidenza": 99, "motivazione": "x"}, "", "m"))["chieste_ai"], 0)  # stesso contesto
        self.assertFalse(SoftwareAlias.objects.exists())


class ManutenzioneTests(TestCase):
    def setUp(self):
        self.src = SecuritySource.objects.create(name="Fonte manutenzione", source_type=SourceType.choices[0][0])

    def _mail(self, giorni, stato):
        m = SecurityMailboxMessage.objects.create(source=self.src, subject="report", body="testo lungo del report", parse_status=stato)
        SecurityMailboxMessage.objects.filter(pk=m.pk).update(received_at=timezone.now() - timedelta(days=giorni))
        return m

    def test_pulizia_svuota_solo_il_grezzo_vecchio_gia_letto(self):
        vecchia, recente, fallita = self._mail(200, ParseStatus.PARSED), self._mail(5, ParseStatus.PARSED), self._mail(200, ParseStatus.FAILED)
        esito = manutenzione_soc.pulizia()
        self.assertEqual(esito["mail_svuotate"], 1)
        vecchia.refresh_from_db(); recente.refresh_from_db(); fallita.refresh_from_db()  # noqa: E702
        self.assertEqual((vecchia.body, vecchia.subject), ("", "report"))  # la riga resta
        self.assertTrue(recente.body and fallita.body)

    def test_postura_fotografata_e_avviso_solo_al_passaggio_sotto_soglia(self):
        oggi = timezone.localdate()
        mappa = {"pcs": [{"key": "pc-a", "nome": "PC-A", "punteggio": 40, "motivo": "Backup fallito", "url": "/soc/pc/?nome=PC-A"},
                         {"key": "pc-b", "nome": "PC-B", "punteggio": 30, "motivo": "x", "url": "/soc/pc/?nome=PC-B"}]}
        PosturaGiorno.objects.create(giorno=oggi - timedelta(days=1), pc="pc-a", punteggio=80)
        PosturaGiorno.objects.create(giorno=oggi - timedelta(days=1), pc="pc-b", punteggio=35)  # era già sotto
        with mock.patch("security.services.postura.mappa", return_value=mappa):
            pcs, ieri = manutenzione_soc.fotografa_postura()
        self.assertEqual(PosturaGiorno.objects.filter(giorno=oggi).count(), 2)
        with mock.patch("security.services.proactive_alerts._channels", return_value=["canale"]), \
                mock.patch("security.services.proactive_alerts._send", return_value=1) as send:
            self.assertEqual(manutenzione_soc.avvisa_postura(pcs, ieri), 1)
        self.assertIn("PC-A: 80 → 40", send.call_args.kwargs["body"])
        self.assertEqual(manutenzione_soc.variazioni({"pc-a": 40, "pc-b": 30, "pc-c": 90}, 1), {"pc-a": -40, "pc-b": -5})


class PagineTests(_Login):
    def test_scheda_pc_kb_storico_versioni_ticket(self):
        DispositivoIntune.objects.create(intune_id="i-kb", nome="PC-ST-01")
        vecchia = _sw("pc-st-01", "google", "google chrome", "130.0", "watchguard", "Google Chrome")
        SoftwareInstallation.objects.filter(pk=vecchia.pk).update(still_detected=False, seen_at=timezone.now() - timedelta(days=20))
        _sw("pc-st-01", "google", "google chrome", "131.0", "watchguard", "Google Chrome")
        WatchGuardAggiornamento.objects.create(host="pc-st-01", nome="KB5046633 aggiornamento cumulativo")
        html = self.client.get(reverse("security:pc_detail") + "?nome=PC-ST-01").content.decode()
        for testo in ("Storico delle versioni", "130.0", "131.0", "KB5046633", "Apri un ticket per questo PC"):
            self.assertIn(testo, html)

    def test_pagina_software_doppioni_e_unisci(self):
        _sw("pc-dp-02", "microsoft", "microsoft teams", "24.1", "watchguard", "Microsoft Teams")
        _sw("pc-dp-02", "microsoft", "teams", "24.1", "defender", "teams")
        p = SecurityPropostaAi.objects.create(tipo=SecurityPropostaAi.TIPO_DOPPIONE, chiave="doppione|microsoft|teams|microsoft|microsoft teams",
                                              vendor="microsoft", product="teams", proposta="microsoft|microsoft teams", confidenza=72,
                                              candidati=[["24.1"], ["24.1"], 1, 1, 0.9], motivazione="nome breve")
        html = self.client.get(reverse("security:software_soc")).content.decode()
        self.assertIn("Doppioni tra le fonti", html)
        self.assertIn("72%", html)
        with mock.patch("security.views_vuln._queue_recompute"):
            r = self.client.post(reverse("security:software_doppione", args=[p.pk]), {"azione": "unisci"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(SoftwareInstallation.objects.filter(host="pc-dp-02", still_detected=True).count(), 1)

    def test_ricerca_programmi_e_ip(self):
        _sw("pc-ri-01", "igor pavlov", "7-zip", "26.05", "watchguard", "7-Zip 26.05")
        from assets.models import IndirizzoRete

        IndirizzoRete.objects.create(ip="10.9.8.7", mac="aa:bb:cc:dd:ee:ff", nome_dhcp="PC-RI-02.dominio.local", nel_dhcp=True)
        self.assertContains(self.client.get(reverse("security:search") + "?q=7-zip"), "installato su 1 PC")
        r = self.client.get(reverse("security:search") + "?q=10.9.8.7")
        self.assertContains(r, "PC-RI-02")
        self.assertContains(r, "IP 10.9.8.7")

    def test_eventi_con_alert_portano_all_alert(self):
        src = SecuritySource.objects.create(name="Fonte eventi", source_type=SourceType.choices[0][0])
        asset = SecurityAsset.objects.create(hostname="PC-EV-01", source=src)
        ev = SecurityEventRecord.objects.create(source=src, asset=asset, event_type="malware", fingerprint="f", dedup_hash="f")
        alert = SecurityAlert.objects.create(source=src, event=ev, title="Malware", severity="high", dedup_hash="a")
        self.assertContains(self.client.get(reverse("security:events")), f"Alert #{alert.pk}")


class CpeAutomaticoTests(TestCase):
    def _proposta(self, proposta, confidenza):
        return SecurityPropostaAi.objects.create(tipo=SecurityPropostaAi.TIPO_CPE, chiave=f"cpe|acme|viewer|{proposta}|{confidenza}",
                                                 vendor="acme", product="viewer", proposta=proposta, confidenza=confidenza)

    def test_solo_collegamenti_sicuri_si_accettano_da_soli(self):
        from security.models import SoftwareCpeMapping
        from security.services import cpe_ai

        with mock.patch("security.services.cve_feeds.queue_recompute"):
            self.assertFalse(cpe_ai.accetta_se_sicura(self._proposta("acme:viewer", 80)))          # sotto soglia
            self.assertFalse(cpe_ai.accetta_se_sicura(self._proposta(SecurityPropostaAi.NON_APPLICABILE, 99)))  # mai «non applicabile»
            sicura = self._proposta("acme:viewer", 95)
            self.assertTrue(cpe_ai.accetta_se_sicura(sicura))
        m = SoftwareCpeMapping.objects.get(vendor="acme", product="viewer")
        self.assertEqual((m.cpe_vendor, m.cpe_product, m.confirmed, m.not_applicable), ("acme", "viewer", True, False))
        sicura.refresh_from_db()
        self.assertEqual(sicura.stato, SecurityPropostaAi.ACCETTATA)
