"""Dotazione software attesa e hardware a fine vita. Dati sintetici."""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset, DispositivoIntune, SoftwareDotazioneAttesa
from assets.services import hardware_vita, software_dotazione
from security.models import SoftwareInstallation

OGGI = date(2026, 11, 8)


def _sw(host, vendor, product, hub, version="1.0"):
    now = timezone.now()
    return SoftwareInstallation.objects.create(
        dedup_key=f"{host}|{vendor}|{product}|{version}", source_kind="watchguard", fonti=["watchguard"], host=host, host_display=host,
        hub_asset=hub, vendor=vendor, vendor_raw=vendor, product=product, product_raw=product, version_raw=version,
        still_detected=True, seen_at=now, last_seen_at=now,
    )


class _Base(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_superuser("dot-demo", "dot@example.test", "x")
        UserOnboarding.objects.create(user=self.user, completed=True)
        self.client.force_login(self.user)
        self.pc1 = Asset.objects.create(asset_tag="PC-D1", name="PC officina 1", asset_type=Asset.TYPE_PC, reparto="Officina")
        self.pc2 = Asset.objects.create(asset_tag="PC-D2", name="PC ufficio", asset_type=Asset.TYPE_PC, reparto="Ufficio")
        self.srv = Asset.objects.create(asset_tag="SRV-D1", name="Server", asset_type=Asset.TYPE_SERVER)
        self.vuoto = Asset.objects.create(asset_tag="PC-D3", name="PC senza inventario", asset_type=Asset.TYPE_PC, reparto="Officina")
        _sw("pc1", "acme", "acme antivirus 2025", self.pc1)
        _sw("pc2", "acme", "acme antivirus 2026", self.pc2)
        _sw("pc2", "demo", "demo cam", self.pc2)
        _sw("srv", "demo", "demo backup agent", self.srv)


class DotazioneTests(_Base):
    def test_manca_dove_non_c_e_nessun_nome_del_programma(self):
        SoftwareDotazioneAttesa.objects.create(programma="acme|acme antivirus 2025", etichetta="Acme Antivirus", ambito="tutti")
        SoftwareDotazioneAttesa.objects.create(programma="demo|demo cam", etichetta="Demo CAM", ambito="pc", reparto="Officina")
        esiti = {str(r["regola"]): r for r in software_dotazione.scostamenti()}
        av = esiti["Acme Antivirus su PC, notebook e server"]
        self.assertEqual([a.name for a in av["mancanti"]], ["Server"])   # il 2026 vale come il 2025
        self.assertEqual((av["coperti"], av["senza_inventario"]), (2, 1))
        cam = esiti["Demo CAM su PC e notebook del reparto Officina"]
        self.assertEqual([a.name for a in cam["mancanti"]], ["PC officina 1"])
        self.assertEqual(software_dotazione.mancanti_per_asset(self.pc1), ["Demo CAM"])
        self.assertEqual(software_dotazione.mancanti_per_asset(self.pc2), [])
        self.assertEqual(software_dotazione.mancanti_per_asset(self.vuoto), [])
        self.assertEqual(software_dotazione.totale_mancanti(), 2)

    def test_dismessi_non_contano(self):
        self.srv.status = Asset.STATUS_RETIRED
        self.srv.save()
        SoftwareDotazioneAttesa.objects.create(programma="acme|acme antivirus 2025", etichetta="Acme Antivirus", ambito="tutti")
        self.assertEqual(software_dotazione.scostamenti()[0]["mancanti"], [])

    def test_dalla_pagina_aggiungi_e_togli(self):
        url = reverse("assets:software_catalog")
        risposta = self.client.post(url, {"azione": "dotazione_aggiungi", "programma": "demo|demo cam", "ambito": "pc", "reparto": "Officina"})
        self.assertEqual(risposta.status_code, 302)
        regola = SoftwareDotazioneAttesa.objects.get()
        self.assertEqual((regola.etichetta.casefold(), regola.ambito, regola.reparto), ("demo cam", "pc", "Officina"))
        pagina = self.client.get(url)
        self.assertContains(pagina, "manca su 1 PC")
        self.assertContains(pagina, "PC officina 1")
        self.assertContains(pagina, "copertura 0%")  # pc1 è l'unico PC del reparto Officina con inventario e non ha il CAM
        self.assertContains(pagina, 'class="sc-dot-bar"')
        self.assertContains(pagina, 'class="sc-chip"')
        self.client.post(url, {"azione": "dotazione_togli", "regola": regola.pk})
        self.assertFalse(SoftwareDotazioneAttesa.objects.exists())

    def test_programma_non_in_catalogo_rifiutato(self):
        self.client.post(reverse("assets:software_catalog"), {"azione": "dotazione_aggiungi", "programma": "x|inesistente", "ambito": "pc"})
        self.assertFalse(SoftwareDotazioneAttesa.objects.exists())


class FineVitaTests(_Base):
    def test_giudizi(self):
        self.pc1.purchase_date = OGGI - timedelta(days=int(6.5 * 365.25))
        self.pc1.save()
        v = hardware_vita.valuta(self.pc1, OGGI)
        self.assertEqual(v["giudizio"], hardware_vita.SOSTITUIRE)
        self.assertIn("anni", v["motivi"][0])
        self.pc2.purchase_date = OGGI - timedelta(days=int(5.2 * 365.25))
        self.pc2.warranty_end = OGGI + timedelta(days=30)
        self.pc2.save()
        v = hardware_vita.valuta(self.pc2, OGGI)
        self.assertEqual(v["giudizio"], hardware_vita.PIANIFICARE)
        self.assertEqual(len(v["motivi"]), 2)
        self.assertEqual(hardware_vita.valuta(self.srv, OGGI)["giudizio"], hardware_vita.NON_VALUTABILE)

    def test_ram_bassa_e_disco_pieno_da_intune(self):
        DispositivoIntune.objects.create(intune_id="i1", nome="PC ufficio", asset=self.pc2, ram_bytes=4 * 1024 ** 3,
                                         disco_totale_bytes=100 * 1024 ** 3, disco_libero_bytes=5 * 1024 ** 3)
        v = hardware_vita.valuta(self.pc2, OGGI)
        self.assertEqual(v["giudizio"], hardware_vita.SOSTITUIRE)
        self.assertEqual(v["motivi"], ["4 GB di RAM", "disco pieno al 95%"])
        DispositivoIntune.objects.create(intune_id="i2", nome="Server", asset=self.srv, ram_bytes=4 * 1024 ** 3)
        self.assertEqual(hardware_vita.valuta(self.srv, OGGI)["giudizio"], hardware_vita.OK)  # la RAM bassa vale solo per i PC

    def test_garanzia_scaduta_con_guasti(self):
        from tickets.models import Ticket, TipoTicket

        self.pc1.warranty_end = OGGI - timedelta(days=10)
        self.pc1.save()
        self.assertEqual(hardware_vita.valuta(self.pc1, OGGI)["giudizio"], hardware_vita.PIANIFICARE)
        for i in range(3):
            Ticket.objects.create(tipo=TipoTicket.IT, titolo=f"Guasto {i}", descrizione="x", categoria="PC", richiedente_nome="Tester", asset=self.pc1)
        v = hardware_vita.valuta(self.pc1, OGGI)
        self.assertEqual((v["giudizio"], v["guasti"]), (hardware_vita.SOSTITUIRE, 3))

    def test_elenco_e_scheda(self):
        self.pc1.purchase_date = OGGI - timedelta(days=int(7 * 365.25))
        self.pc1.save()
        righe = hardware_vita.elenco(OGGI)
        self.assertEqual(righe[0]["asset"].name, "PC officina 1")
        self.assertEqual(hardware_vita.conteggi(righe)["sostituire"], 1)
        pagina = self.client.get(reverse("assets:it_reconciliation") + "?vista=fine_vita")
        self.assertContains(pagina, "Hardware a fine vita")
        self.assertContains(pagina, "Da sostituire")
        self.assertContains(pagina, "PC officina 1")
        self.assertContains(pagina, 'class="rc-fv-track"')
        self.assertContains(pagina, "Come giudico")
        # i contatori filtrano la tabella
        solo = self.client.get(reverse("assets:it_reconciliation") + "?vista=fine_vita&giudizio=sostituire")
        self.assertContains(solo, "PC officina 1")
        self.assertNotContains(solo, "PC ufficio")
        self.assertContains(solo, "1 su 4 PC, notebook e server")
        nessuno = self.client.get(reverse("assets:it_reconciliation") + "?vista=fine_vita&giudizio=pianificare")
        self.assertContains(nessuno, "Nessun asset con questo giudizio")
        self.assertEqual(hardware_vita.filtra(righe, "farlocco"), righe)
        self.assertEqual((hardware_vita.eta_percento(None), hardware_vita.eta_percento(0.05), hardware_vita.eta_percento(4), hardware_vita.eta_percento(12)),
                         (None, 2, 50, 100))

    def test_campo_fine_garanzia_nel_form(self):
        from assets.forms import AssetForm

        self.assertIn("warranty_end", AssetForm.Meta.fields)
