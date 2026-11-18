"""KPI cliccabili di Persone, struttura, recruiting e reportistica (gruppo 2).

Il contratto di ogni tessera: il link porta a una pagina che, con il filtro
dell'URL, mostra esattamente l'insieme che la tessera conta. Qui si verifica
l'href della tessera e che la destinazione conti lo stesso numero.
"""
from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AdempimentoCambioMansione, CentroDiCosto, DipendenteAssegnazione, Reparto
from .models_recruiting import Candidato, PosizioneAperta
from .models_reportistica import ReportGenerato
from .tests import _ensure_anagrafica_table

User = get_user_model()

RIGHE = [
    {"id": 1, "utente_id": 0, "nome": "Anna", "cognome": "Attiva", "reparto": "Montaggio", "mansione": "",
     "matricola": "1", "aliasusername": "a.attiva", "email_notifica": "", "attivo": True},
    {"id": 2, "utente_id": 0, "nome": "Carlo", "cognome": "Escluso", "reparto": "Direzione", "mansione": "",
     "matricola": "2", "aliasusername": "c.escluso", "email_notifica": "", "attivo": True},
    {"id": 3, "utente_id": 0, "nome": "Dario", "cognome": "Spento", "reparto": "Montaggio", "mansione": "",
     "matricola": "3", "aliasusername": "d.spento", "email_notifica": "", "attivo": False},
    {"id": 4, "utente_id": 0, "nome": "Elena", "cognome": "Seconda", "reparto": "Verniciatura", "mansione": "",
     "matricola": "4", "aliasusername": "e.seconda", "email_notifica": "", "attivo": True},
]


class _Admin(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser("kpi-g2", "kpi-g2@test.local", "x")

    def setUp(self):
        self.client.force_login(self.admin)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DipendentiKpiTests(_Admin):
    """«Attivi», «Fuori conteggio», «Non attivi», «Reparti» e la dashboard che li riprende."""

    def setUp(self):
        super().setUp()
        for patch in (
            mock.patch("anagrafica.views.dipendenti._dipendenti_base_rows", side_effect=lambda: [dict(r) for r in RIGHE]),
            mock.patch("anagrafica.views._helpers._cessati_legacy_ids", return_value=set()),
            mock.patch("anagrafica.services.conteggi_organico.esclusi_dai_conteggi_ids", return_value={2}),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def _elenco(self, **params):
        return self.client.get(reverse("anagrafica:dipendenti_list"), params)

    def test_kpi_di_stato_sommano_a_in_elenco(self):
        ctx = self._elenco().context
        self.assertEqual((ctx["n_attivi"], ctx["n_esclusi_conteggi"], ctx["n_non_attivi"]), (2, 1, 1))
        self.assertEqual(ctx["n_attivi"] + ctx["n_esclusi_conteggi"] + ctx["n_non_attivi"], ctx["n_totale"])

    def test_ogni_tessera_apre_l_elenco_che_conta_lo_stesso_numero(self):
        resp = self._elenco()
        base = reverse("anagrafica:dipendenti_list")
        for stato, chiave in (("attivi", "n_attivi"), ("fuori_conteggio", "n_esclusi_conteggi"),
                              ("non_attivi", "n_non_attivi")):
            with self.subTest(stato=stato):
                self.assertContains(resp, f'href="{base}?stato={stato}&amp;vf=0#elenco"')
                filtrato = self._elenco(stato=stato, vf="0")
                self.assertEqual(filtrato.context["page_obj"].paginator.count, resp.context[chiave])

    def test_reparti_conta_le_schede_della_griglia(self):
        resp = self._elenco()
        # Organico (senza l'escluso): Montaggio e Verniciatura; «Direzione» è solo dell'escluso.
        self.assertEqual(resp.context["n_reparti"], 2)
        schede = [s for s in resp.context["reparti_griglia"]["schede"] if s["titolo"] != "Senza reparto"]
        self.assertEqual(len(schede), resp.context["n_reparti"])
        self.assertContains(resp, "#fmd-reparti")

    def test_dashboard_dipendenti_uguale_agli_attivi_dell_elenco(self):
        dash = self.client.get(reverse("anagrafica:index"))
        self.assertEqual(dash.context["n_dipendenti"], self._elenco().context["n_attivi"])
        self.assertContains(dash, reverse("anagrafica:dipendenti_list") + "?stato=attivi&amp;vf=0#elenco")

    def test_stato_non_valido_e_ignorato(self):
        self.assertEqual(self._elenco(stato="boh").context["page_obj"].paginator.count, len(RIGHE))


class RepartiECentriKpiTests(_Admin):
    def setUp(self):
        super().setUp()
        Reparto.objects.create(nome="Produzione")
        Reparto.objects.create(nome="Qualità")
        Reparto.objects.create(nome="Chiuso", is_active=False)
        CentroDiCosto.objects.create(nome="CdC attivo")
        CentroDiCosto.objects.create(nome="CdC spento", is_active=False)

    def test_reparti_attivi_apre_le_sole_schede_attive(self):
        resp = self.client.get(reverse("anagrafica:aree_list"))
        self.assertContains(resp, reverse("anagrafica:aree_list") + "?filtro=attivi#schede")
        filtrato = self.client.get(reverse("anagrafica:aree_list"), {"filtro": "attivi"})
        self.assertEqual(len(filtrato.context["schede"]), resp.context["kpi"]["reparti"])
        self.assertEqual(resp.context["kpi"]["reparti"], 2)

    def test_reparti_da_sistemare_stessa_regola(self):
        resp = self.client.get(reverse("anagrafica:aree_list"))
        filtrato = self.client.get(reverse("anagrafica:aree_list"), {"filtro": "da_sistemare"})
        self.assertEqual(len(filtrato.context["schede"]), resp.context["kpi"]["da_sistemare"])

    def test_dashboard_reparti_catalogo_porta_ai_reparti_attivi(self):
        dash = self.client.get(reverse("anagrafica:index"))
        self.assertContains(dash, reverse("anagrafica:aree_list") + "?filtro=attivi#schede")
        filtrato = self.client.get(reverse("anagrafica:aree_list"), {"filtro": "attivi"})
        self.assertEqual(len(filtrato.context["schede"]), dash.context["n_reparti_catalog"])

    def test_centri_attivi_apre_i_soli_centri_attivi(self):
        resp = self.client.get(reverse("anagrafica:centri_costo"))
        self.assertContains(resp, reverse("anagrafica:centri_costo") + "?filtro=attivi#centri")
        filtrato = self.client.get(reverse("anagrafica:centri_costo"), {"filtro": "attivi"})
        self.assertEqual(len(filtrato.context["schede"]), resp.context["kpi"]["centri"])
        self.assertEqual(resp.context["kpi"]["centri"], 1)

    def test_dashboard_mansioni_e_tipi_qualifica_aprono_il_solo_catalogo_attivo(self):
        from .models import Mansione, TipoQualifica

        Mansione.objects.create(nome="Saldatore")
        Mansione.objects.create(nome="Dismessa", is_active=False)
        TipoQualifica.objects.create(nome="Carrellista")
        TipoQualifica.objects.create(nome="Vecchia", is_active=False)
        dash = self.client.get(reverse("anagrafica:index"))
        self.assertContains(dash, reverse("anagrafica:mansioni_list") + "?solo_attive=1")
        self.assertContains(dash, reverse("anagrafica:qualifiche_list") + "?attivi=1")
        mansioni = self.client.get(reverse("anagrafica:mansioni_list"), {"solo_attive": "1"})
        self.assertEqual(len(mansioni.context["mansioni"]), dash.context["n_mansioni"])
        tipi = self.client.get(reverse("anagrafica:qualifiche_list"), {"attivi": "1"})
        self.assertEqual(len(tipi.context["tipi"]), dash.context["n_qualifiche"])


class RecruitingKpiTests(_Admin):
    def setUp(self):
        super().setUp()
        oggi = timezone.localdate()
        PosizioneAperta.objects.create(titolo="In ritardo", data_richiesta=oggi - timedelta(days=40),
                                       entro_il=oggi - timedelta(days=5))
        PosizioneAperta.objects.create(titolo="In tempo", data_richiesta=oggi, entro_il=oggi + timedelta(days=30))
        PosizioneAperta.objects.create(titolo="Coperta ora", data_richiesta=oggi - timedelta(days=30),
                                       stato=PosizioneAperta.STATO_COPERTA, chiusa_il=oggi - timedelta(days=2))
        PosizioneAperta.objects.create(titolo="Coperta vecchia", data_richiesta=oggi - timedelta(days=900),
                                       stato=PosizioneAperta.STATO_COPERTA, chiusa_il=oggi - timedelta(days=500))
        Candidato.objects.create(cognome="Uno", nome="A", stato=Candidato.STATO_ASSUNTO,
                                 giudizio_finale=Candidato.GIUDIZIO_POSITIVO)
        Candidato.objects.create(cognome="Due", nome="B", stato=Candidato.STATO_OFFERTA)
        Candidato.objects.create(cognome="Tre", nome="C", giudizio_finale=Candidato.GIUDIZIO_NEGATIVO)
        Candidato.objects.create(cognome="Quattro", nome="D", stato=Candidato.STATO_IN_DATABASE)

    def test_posizioni_in_ritardo_e_coperte_12_mesi(self):
        resp = self.client.get(reverse("anagrafica:recruiting_posizioni"))
        kpi = resp.context["kpi"]
        base = reverse("anagrafica:recruiting_posizioni")
        self.assertContains(resp, base + "?ritardo=1")
        self.assertContains(resp, base + "?periodo=12m")
        ritardo = self.client.get(base, {"ritardo": "1"})
        self.assertEqual(len(ritardo.context["righe"]), kpi["in_ritardo"])
        coperte = self.client.get(base, {"periodo": "12m"})
        self.assertEqual(len(coperte.context["righe"]), kpi["coperte_12m"])
        self.assertEqual((kpi["in_ritardo"], kpi["coperte_12m"]), (1, 1))

    def test_cruscotto_candidati_apre_l_elenco_con_lo_stesso_numero(self):
        resp = self.client.get(reverse("anagrafica:recruiting_dashboard"))
        kpi, urls = resp.context["kpi"], resp.context["kpi_url"]
        for chiave, atteso in (("tutti", kpi["totale"]), ("assunti", kpi["assunti"]),
                               ("offerte", kpi["offerte"]), ("positivi", kpi["positivi"]),
                               ("negativi", kpi["negativi"])):
            with self.subTest(kpi=chiave):
                self.assertContains(resp, f'href="{urls[chiave]}"')
                self.assertEqual(self.client.get(urls[chiave]).context["totale"], atteso)

    def test_elenco_iter_aperti_assunti_database(self):
        resp = self.client.get(reverse("anagrafica:recruiting_list"))
        base = reverse("anagrafica:recruiting_list")
        for stato, chiave in (("in_corso", "n_in_corso"), ("ASSUNTO", "n_assunti"), ("IN_DATABASE", "n_in_database")):
            with self.subTest(stato=stato):
                self.assertContains(resp, f'href="{base}?stato={stato}"')
                self.assertEqual(self.client.get(base, {"stato": stato}).context["totale"], resp.context[chiave])


class ReportisticaKpiTests(_Admin):
    def _doc(self, **extra):
        return ReportGenerato.objects.create(titolo="Doc", formato="pdf", nome_file="x.pdf", contenuto=b"x",
                                            generato_da=self.admin, **extra)

    def test_archivio_filtrato_conta_come_il_kpi(self):
        self._doc(contiene_dati_personali=True)
        self._doc()
        vecchio = self._doc()
        ReportGenerato.objects.filter(pk=vecchio.pk).update(generato_il=timezone.now() - timedelta(days=45))
        resp = self.client.get(reverse("anagrafica:reportistica_index"))
        base = reverse("anagrafica:reportistica_index")
        for filtro, chiave in (("30g", "ultimi_30"), ("dati_personali", "dati_personali")):
            with self.subTest(filtro=filtro):
                self.assertContains(resp, f"{base}?filtro={filtro}#archivio")
                filtrato = self.client.get(base, {"filtro": filtro})
                self.assertEqual(filtrato.context["n_archivio"], resp.context["kpi"][chiave])
        self.assertEqual((resp.context["kpi"]["ultimi_30"], resp.context["kpi"]["dati_personali"]), (2, 1))


class CambiMansioneKpiTests(_Admin):
    def test_da_fare_conta_solo_gli_adempimenti_attivi_come_l_elenco(self):
        oggi = timezone.localdate()
        ass = DipendenteAssegnazione.objects.create(legacy_anagrafica_id=11, data_inizio=oggi - timedelta(days=3))
        AdempimentoCambioMansione.objects.create(assegnazione=ass, legacy_anagrafica_id=11, tipo="FORMAZIONE", descrizione="Corso",
                                                 entro_il=oggi - timedelta(days=1))
        AdempimentoCambioMansione.objects.create(assegnazione=ass, legacy_anagrafica_id=11, tipo="VISITA", descrizione="Visita",
                                                 entro_il=oggi + timedelta(days=10), attivo=False)
        with mock.patch("anagrafica.services.cambio_mansione.aggiorna_piani"):
            resp = self.client.get(reverse("anagrafica:cambi_mansione"), {"stato": "aperti"})
            ritardo = self.client.get(reverse("anagrafica:cambi_mansione"), {"stato": "ritardo"})
        voci = sum(len(p["voci"]) for p in resp.context["gruppi"])
        self.assertEqual(voci, resp.context["n_aperti"])
        self.assertEqual(sum(len(p["voci"]) for p in ritardo.context["gruppi"]), resp.context["n_ritardo"])
        self.assertContains(resp, reverse("anagrafica:cambi_mansione") + "?stato=ritardo")


class CostoOrarioKpiTests(_Admin):
    def test_i_kpi_non_cambiano_con_mostra_e_aprono_lo_stesso_insieme(self):
        from decimal import Decimal as D

        from .models import CostoOrarioMensile

        prima, mese = date(2026, 9, 1), date(2026, 10, 1)
        for cf, c_prima, c_mese, manuale in (("AAAAAA00A00A000A", "10", "12", False),
                                             ("BBBBBB00B00B000B", "20", "18", True),
                                             ("CCCCCC00C00C000C", "15", "15", False)):
            for m, c in ((prima, c_prima), (mese, c_mese)):
                CostoOrarioMensile.objects.create(tax_code=cf, mese=m, rml=D("1000"), divisore_giorni=D("26"),
                                                  divisore_ore=D("6.66"), costo_orario=D(c),
                                                  rml_manuale=manuale and m == mese)
        base = reverse("anagrafica:costo_orario")
        tutto = self.client.get(base, {"mese": mese.isoformat()})
        kpi = tutto.context["kpi"]
        self.assertEqual((kpi["aumentati"], kpi["diminuiti"], kpi["manuali"]), (1, 1, 1))
        con_mostra = self.client.get(base, {"mese": mese.isoformat(), "mostra": "aumentati"})
        self.assertEqual(con_mostra.context["kpi"], kpi)
        for chiave in ("aumentati", "diminuiti", "manuali", "lontani"):
            with self.subTest(kpi=chiave):
                url = tutto.context["kpi_url"][chiave]
                self.assertContains(tutto, f'href="{url.replace("&", "&amp;")}"')
                self.assertEqual(len(self.client.get(url).context["righe"]), kpi[chiave])
