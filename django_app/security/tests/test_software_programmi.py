"""Catalogo software: release, lingue e produttori diversi dello stesso programma sono una riga sola."""
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from assets.models import SoftwareCatalogEntry, SoftwareLicense
from assets.views_software import _filter, catalog_rows
from security.models import SoftwareInstallation, SoftwareProgrammaRegola
from security.services import software_catalog as sc
from security.services.software_inventory import nome_programma


class NomeProgrammaTests(SimpleTestCase):
    def test_toglie_la_release(self):
        casi = {
            "7-Zip 26.05 (x64 edition)": "7-Zip",
            "7-Zip 26.05 (x64)": "7-Zip",
            "7-zip 25.01 ( edition)": "7-zip",
            "Java 8 Update 381": "Java 8",
            "Mozilla Firefox 88.0.1 (x64 it)": "Mozilla Firefox",
            "Microsoft 365 Apps for business - it-it": "Microsoft 365 Apps for business",
            "Adobe Reader XI (11.0.12) - italiano": "Adobe Reader XI",
            "Windows 11 Pro 64 bits version 24H2": "Windows 11 Pro",
            "Intr@Web-Client-19.0.0.0": "Intr@Web-Client",
            "WinAppRuntime.Main.1.8": "WinAppRuntime.Main",
            "hyperMILL 2024 SUITE | Update 5": "hyperMILL SUITE",
            "Peugeot Update 1.5.1": "Peugeot Update",
            "Pacchetto driver Windows - Demo (usbser) Ports  (01/05/2012 2.0.1.0)": "Pacchetto driver Windows - Demo (usbser) Ports",
        }
        for grezzo, atteso in casi.items():
            with self.subTest(grezzo):
                self.assertEqual(nome_programma(grezzo), atteso)

    def test_il_numero_del_nome_resta(self):
        for nome in ("Windows 10", "Microsoft 365", "Microsoft Visual C++ 2013 Redistributable", "Microsoft Visual C++ 2015-2022 Redistributable",
                     "PostgreSQL 15", "Intel(R) USB 3.0 eXtensible Host Controller Driver", "Microsoft Teams (personal)"):
            with self.subTest(nome):
                self.assertEqual(nome_programma(nome), nome)

    def test_anno_con_punto_come_anno_senza(self):
        self.assertEqual(nome_programma("hyperMILL 2023.2 License Manager"), "hyperMILL License Manager")
        self.assertEqual(nome_programma("hyperMILL 2024 License Manager"), "hyperMILL License Manager")

    def test_toglie_l_anno(self):
        for grezzo, atteso in {"MUD 2024": "MUD", "Microsoft Office Enterprise 2007": "Microsoft Office Enterprise", "mtb2011": "mtb2011", "2024": "2024"}.items():
            with self.subTest(grezzo):
                self.assertEqual(nome_programma(grezzo), atteso)

    def test_nome_fatto_solo_di_versione_resta(self):
        self.assertEqual(nome_programma("26.05"), "26.05")


def _sw(host, vendor, product, version="1.0", *, raw=None, vendor_raw=None, still=True):
    now = timezone.now()
    return SoftwareInstallation.objects.create(
        dedup_key=f"{host}|{vendor}|{product}|{version}", source_kind="watchguard", host=host, host_display=host,
        vendor=vendor, vendor_raw=vendor if vendor_raw is None else vendor_raw, product=product, product_raw=raw or product,
        version_raw=version, still_detected=still, seen_at=now, last_seen_at=now,
    )


class ProgrammiTests(TestCase):
    def test_le_release_diventano_una_riga(self):
        _sw("pc1", "igor pavlov", "7-zip 25.01 ( edition)", "25.01", raw="7-Zip 25.01 (x64 edition)", vendor_raw="Igor Pavlov")
        _sw("pc2", "igor pavlov", "7-zip 26.05 ( edition)", "26.05", raw="7-Zip 26.05 (x64 edition)", vendor_raw="Igor Pavlov")
        _sw("pc3", "igor pavlov", "7-zip 26.05", "26.05", raw="7-Zip 26.05 (x64)", vendor_raw="Igor Pavlov")
        righe = catalog_rows(with_cve=False)
        self.assertEqual(len(righe), 1)
        self.assertEqual((righe[0]["name"], righe[0]["vendor"], righe[0]["hosts"], righe[0]["versions"], righe[0]["names"]),
                         ("7-Zip", "Igor Pavlov", 3, 2, 3))

    def test_stesso_nome_produttori_scritti_diversi(self):
        _sw("pc1", "acro software", "cutepdf writer", "4.0", raw="CutePDF Writer", vendor_raw="Acro Software Inc.")
        _sw("pc1", "acrosoftware", "cutepdf writer", "4.0", raw="cutepdf writer", vendor_raw="acrosoftware")
        _sw("pc2", "acrosoftware", "cutepdf writer", "4.1", raw="cutepdf writer", vendor_raw="acrosoftware")
        righe = catalog_rows(with_cve=False)
        self.assertEqual(len(righe), 1)
        self.assertEqual((righe[0]["name"], righe[0]["hosts"]), ("CutePDF Writer", 2))

    def test_il_produttore_uguale_al_programma_non_vince(self):
        _sw("pc1", "7-zip", "7-zip", "26.05", raw="7-zip", vendor_raw="7-zip")
        _sw("pc2", "7-zip", "7-zip", "26.05", raw="7-zip", vendor_raw="7-zip")
        _sw("pc3", "igor pavlov", "7-zip", "26.05", raw="7-Zip", vendor_raw="Igor Pavlov")
        riga = catalog_rows(with_cve=False)[0]
        self.assertEqual((riga["name"], riga["vendor"], riga["hosts"]), ("7-Zip", "Igor Pavlov", 3))

    def test_non_fonde_programmi_diversi(self):
        for vendor, product in (("autodesk", "autodesk access"), ("microsoft", "microsoft access"),
                                ("docker", "docker desktop"), ("github", "github desktop"),
                                ("microsoft", "windows 10"), ("microsoft", "windows 11"),
                                ("microsoft", "microsoft visual c++ 2013 redistributable"), ("microsoft", "microsoft visual c++ 2015 redistributable"),
                                ("microsoft", "ms-resource:appname"), ("clipchamp", "ms-resource:appname")):
            _sw("pc1", vendor, product)
        self.assertEqual(len(catalog_rows(with_cve=False)), 10)

    def test_ricerca_senza_trattini_e_sui_nomi_originali(self):
        _sw("pc1", "igor pavlov", "7-zip 26.05", "26.05", raw="7-Zip 26.05 (x64)", vendor_raw="Igor Pavlov")
        _sw("pc1", "microsoft", "windows 11")
        righe = catalog_rows(with_cve=False)
        for q in ("7zip", "7-ZIP", "26.05", "x64", "pavlov zip"):
            with self.subTest(q):
                self.assertEqual([r["name"] for r in _filter(righe, "all", q)], ["7-Zip"])

    def test_decisione_e_licenza_sopravvivono_all_aggiornamento(self):
        """Presa su un nome con la release: quel nome sparisce dall'inventario, la decisione resta del programma."""
        vecchia = sc.inventory_key("igor pavlov", "7-zip 25.01")
        SoftwareCatalogEntry.objects.create(inventory_key=vecchia, display_name="7-Zip 25.01 (x64)", classification=SoftwareCatalogEntry.CLASS_FORBIDDEN)
        SoftwareLicense.objects.create(product_name="Demo 7-Zip", inventory_key=vecchia, seats_total=5)
        _sw("pc1", "igor pavlov", "7-zip 25.01", "25.01", still=False)
        _sw("pc1", "igor pavlov", "7-zip 26.05", "26.05", raw="7-Zip 26.05 (x64)", vendor_raw="Igor Pavlov")
        riga = catalog_rows(with_cve=False)[0]
        self.assertEqual(riga["classification"], SoftwareCatalogEntry.CLASS_FORBIDDEN)
        self.assertEqual(riga["name"], "7-Zip")
        self.assertEqual(riga["license_state"], "coperta")
        self.assertEqual(riga["seats"], 5)
        self.assertEqual(sc.hosts_by_key({vecchia}), {vecchia: 1})
        self.assertEqual([i.version_raw for i in sc.product_hosts(vecchia)], ["26.05"])

    def test_chiave_canonica_preferisce_il_nome_senza_release(self):
        _sw("pc1", "igor pavlov", "7-zip 26.05", "26.05")
        _sw("pc2", "igor pavlov", "7-zip 26.05", "26.05")
        _sw("pc3", "7-zip", "7-zip", "26.05")
        self.assertEqual(sc.chiave_canonica(sc.inventory_key("igor pavlov", "7-zip 26.05")), sc.inventory_key("7-zip", "7-zip"))

    def test_stesso_programma(self):
        self.assertTrue(sc.stesso_programma("igor pavlov", "7-zip 25.01", "7-zip", "7-zip"))
        self.assertFalse(sc.stesso_programma("autodesk", "autodesk access", "microsoft", "microsoft access"))


class RegoleAManoTests(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_superuser("regole-demo", "regole@example.test", "x")
        self.client.force_login(self.user)
        UserOnboarding.objects.update_or_create(user=self.user, defaults={"completed": True})
        self.url = reverse("assets:software_catalog_detail")
        _sw("pc1", "demo", "demo suite 2024", "24.1", raw="Demo Suite 2024")
        _sw("pc2", "demo", "demo suite 2025", "25.1", raw="Demo Suite 2025")
        _sw("pc3", "altro", "altro programma", "1.0", raw="Altro Programma")
        self.k24, self.k25, self.kaltro = "demo|demo suite 2024", "demo|demo suite 2025", "altro|altro programma"

    def _programmi(self):
        return {tuple(sorted(sc.member_keys(r["key"]))) for r in catalog_rows(with_cve=False)}

    def test_le_edizioni_annuali_sono_unite(self):
        self.assertEqual(self._programmi(), {(self.k24, self.k25), (self.kaltro,)})

    def test_separa_e_rimetti(self):
        self.client.post(self.url, {"k": self.k24, "azione": "separa", "membro": self.k25})
        self.assertEqual(self._programmi(), {(self.k24,), (self.k25,), (self.kaltro,)})
        self.assertEqual(sc.chiave_canonica(self.k25), self.k25)
        self.assertEqual({r["name"] for r in catalog_rows(with_cve=False)}, {"Demo Suite", "Demo Suite 2025", "Altro Programma"})
        regola = SoftwareProgrammaRegola.objects.get(tipo="separa")
        pagina = self.client.get(self.url, {"k": self.k25})
        self.assertContains(pagina, "Rimetti nel gruppo")
        self.client.post(self.url, {"k": self.k25, "azione": "annulla_regola", "regola": regola.pk})
        self.assertEqual(self._programmi(), {(self.k24, self.k25), (self.kaltro,)})

    def test_separare_il_nome_con_la_decisione_la_lascia_al_gruppo(self):
        SoftwareCatalogEntry.objects.create(inventory_key=self.k24, classification=SoftwareCatalogEntry.CLASS_FORBIDDEN)
        SoftwareLicense.objects.create(product_name="Demo", inventory_key=self.k24)
        self.client.post(self.url, {"k": self.k24, "azione": "separa", "membro": self.k24})
        self.assertEqual(SoftwareCatalogEntry.objects.get().inventory_key, self.k25)
        self.assertEqual(SoftwareLicense.objects.get().inventory_key, self.k25)
        righe = {r["key"]: r["classification"] for r in catalog_rows(with_cve=False)}
        self.assertEqual(righe[self.k25], SoftwareCatalogEntry.CLASS_FORBIDDEN)
        self.assertEqual(righe[self.k24], SoftwareCatalogEntry.CLASS_UNREVIEWED)

    def test_non_si_separa_un_nome_solo_o_di_un_altro_programma(self):
        self.client.post(self.url, {"k": self.kaltro, "azione": "separa", "membro": self.kaltro})
        self.client.post(self.url, {"k": self.kaltro, "azione": "separa", "membro": self.k24})
        self.assertFalse(SoftwareProgrammaRegola.objects.exists())

    def test_unisci_vale_per_le_versioni_future_e_si_annulla(self):
        canon = sc.chiave_canonica(self.k24)
        self.client.post(self.url, {"k": self.kaltro, "azione": "unisci", "altro": canon})
        self.assertEqual(self._programmi(), {(self.kaltro, self.k24, self.k25)})
        _sw("pc4", "demo", "demo suite 2026", "26.1", raw="Demo Suite 2026")
        SoftwareInstallation.objects.filter(product="demo suite 2024").update(still_detected=False)
        self.assertEqual(sc.chiave_canonica("demo|demo suite 2026"), sc.chiave_canonica(self.kaltro))
        regola = SoftwareProgrammaRegola.objects.get(tipo="unisci")
        self.client.post(self.url, {"k": self.kaltro, "azione": "annulla_regola", "regola": regola.pk})
        self.assertNotEqual(sc.chiave_canonica("demo|demo suite 2026"), sc.chiave_canonica(self.kaltro))

    def test_unisci_con_due_decisioni_ne_resta_una_con_le_note(self):
        canon = sc.chiave_canonica(self.k24)
        SoftwareCatalogEntry.objects.create(inventory_key=self.kaltro, classification=SoftwareCatalogEntry.CLASS_ALLOWED, notes="Nota A")
        SoftwareCatalogEntry.objects.create(inventory_key=canon, classification=SoftwareCatalogEntry.CLASS_FORBIDDEN, notes="Nota B")
        self.client.post(self.url, {"k": self.kaltro, "azione": "unisci", "altro": canon})
        entry = SoftwareCatalogEntry.objects.get()
        self.assertEqual(entry.classification, SoftwareCatalogEntry.CLASS_ALLOWED)
        self.assertEqual(entry.notes, "Nota A\nNota B")

    def test_unisci_rifiuta_un_programma_che_non_esiste(self):
        self.client.post(self.url, {"k": self.kaltro, "azione": "unisci", "altro": "finto|finto"})
        self.assertFalse(SoftwareProgrammaRegola.objects.exists())

    def test_chi_non_amministra_non_cambia_il_raggruppamento(self):
        from unittest.mock import patch

        with patch("assets.views_software._can_edit", return_value=False):
            risposta = self.client.get(self.url, {"k": self.k24})
            self.assertNotContains(risposta, 'value="separa"')
            self.assertNotContains(risposta, 'value="unisci"')
            self.client.post(self.url, {"k": self.k24, "azione": "separa", "membro": self.k25})
        self.assertFalse(SoftwareProgrammaRegola.objects.exists())


class DettaglioProgrammaTests(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_superuser("programmi-demo", "programmi@example.test", "x")
        self.client.force_login(self.user)
        UserOnboarding.objects.update_or_create(user=self.user, defaults={"completed": True})
        _sw("pc1", "igor pavlov", "7-zip 25.01", "25.01", raw="7-Zip 25.01 (x64)", vendor_raw="Igor Pavlov")
        _sw("pc2", "igor pavlov", "7-zip 26.05", "26.05", raw="7-Zip 26.05 (x64)", vendor_raw="Igor Pavlov")

    def test_il_link_di_una_release_porta_al_programma_e_mostra_i_nomi(self):
        r = self.client.get(reverse("assets:software_catalog_detail"), {"k": "igor pavlov|7-zip 25.01"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["host_count"], 2)
        self.assertContains(r, "Nomi raggruppati in questo programma (2)")
        self.assertContains(r, "7-Zip 26.05 (x64)")

    def test_salvare_da_due_nomi_lascia_una_sola_decisione(self):
        url = reverse("assets:software_catalog_detail")
        for k in ("igor pavlov|7-zip 25.01", "igor pavlov|7-zip 26.05"):
            self.client.post(url, {"k": k, "classification": "consentito", "licensing": "gratuito"})
        self.assertEqual(SoftwareCatalogEntry.objects.count(), 1)

    def test_elenco_con_ricerca(self):
        r = self.client.get(reverse("assets:software_catalog"), {"q": "7zip"})
        self.assertContains(r, "2 nomi raggruppati")
        # la ricerca live della tabella legge il testo della riga: ci devono essere i nomi originali
        self.assertContains(r, "<span hidden>7-Zip 25.01 (x64) 7-Zip 26.05 (x64) Igor Pavlov</span>")

    def test_stessa_versione_scritta_in_modi_diversi(self):
        _sw("pc2", "7-zip", "7-zip", "26.05.0.0")
        _sw("pc2", "igor pavlov", "7-zip 26.05b", "26.05.00.0")
        _sw("pc3", "7-zip", "7-zip", "26.05.0.0")
        r = self.client.get(reverse("assets:software_catalog_detail"), {"k": "7-zip|7-zip"})
        righe = {v["version"]: v["hosts"] for v in r.context["version_rows"]}
        self.assertEqual(righe, {"26.05": 2, "25.01": 1})
        self.assertEqual(sc.versions_by_key()["7-zip|7-zip"], {"26.05": 2, "25.01": 1})

    def test_versione_chiave(self):
        self.assertEqual(sc.versione_chiave("26.05.00.0"), "26.05")
        self.assertEqual(sc.versione_chiave("26.10"), "26.10")
        self.assertEqual(sc.versione_chiave("0.0"), "0")
        self.assertEqual(sc.versione_chiave(""), "")
