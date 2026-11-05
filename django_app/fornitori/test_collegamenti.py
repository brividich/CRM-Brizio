"""Scheda fornitore: manutenzione, copie MFC, scadenze e tecnici. Tutto facoltativo: una ditta senza
dati o un GuestPortal che non risponde non devono dare errori."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Fornitore
from assets.models import Asset, AssistanceContract, WorkOrder
from assets.services.fornitore_manutenzione import rapporto_ditta, un_anno_prima
from contatori.models import Fattura, LetturaContatori, Macchina, RigaFattura

from . import collegamenti as col
from . import guestportal as gp
from .models import FornitoreContatori, IngressoIntervento


def _superuser():
    return get_user_model().objects.create_superuser("admin_forn", "admin@example.local", "x")


def _sezione(fornitore, sezione):
    return reverse("fornitori:fornitore_sezione", args=[fornitore.pk, sezione])


class SchedaTests(TestCase):
    def setUp(self):
        self.client.force_login(_superuser())
        self.f = Fornitore.objects.create(ragione_sociale="Ditta Esempio Srl")

    def test_scheda_con_le_schede_nuove(self):
        r = self.client.get(reverse("fornitori:fornitore_detail", args=[self.f.pk]))
        self.assertEqual(r.status_code, 200)
        for testo in ("tab-manutenzione", "tab-scadenze", "tab-tecnici"):
            self.assertContains(r, testo)
        self.assertContains(r, f'data-sezione="{_sezione(self.f, "tecnici")}"')
        # Nessun fornitore MFC collegato: la scheda delle copie non compare.
        self.assertNotContains(r, 'data-tab="tab-copie"')

    def test_sezioni_vuote_non_danno_errori(self):
        for sezione in ("manutenzione", "scadenze", "tecnici", "copie"):
            with self.subTest(sezione=sezione):
                self.assertEqual(self.client.get(_sezione(self.f, sezione)).status_code, 200)
        self.assertContains(self.client.get(_sezione(self.f, "manutenzione")), "Nessun contratto")

    def test_sezione_inesistente(self):
        self.assertEqual(self.client.get(_sezione(self.f, "boh")).status_code, 404)

    @patch("fornitori.collegamenti.apre", return_value=False)
    def test_senza_permesso_del_modulo_403_json(self, _apre):
        for sezione in ("manutenzione", "copie"):
            with self.subTest(sezione=sezione):
                r = self.client.get(_sezione(self.f, sezione))
                self.assertEqual(r.status_code, 403)
                self.assertEqual(r["Content-Type"], "application/json")

    @patch("fornitori.collegamenti.apre", return_value=False)
    def test_senza_permesso_non_si_vede_la_manutenzione(self, _apre):
        r = self.client.get(reverse("fornitori:fornitore_detail", args=[self.f.pk]))
        self.assertNotContains(r, "tab-manutenzione")


class ManutenzioneTests(TestCase):
    def setUp(self):
        self.user = _superuser()
        self.client.force_login(self.user)
        self.f = Fornitore.objects.create(ragione_sociale="Manutenzioni Esempio Srl")
        self.asset = Asset.objects.create(name="Tornio di prova", asset_tag="TST-1")

    def _odl(self, **kw):
        return WorkOrder.objects.create(asset=self.asset, supplier=self.f, title=kw.pop("title", "Intervento"), **kw)

    def test_stessi_numeri_nella_scheda_e_in_assets(self):
        self._odl(title="Aperto uno")
        self._odl(title="Chiuso uno", status=WorkOrder.STATUS_DONE, closed_at=timezone.now(), cost_eur=120)
        self._odl(title="Chiuso vecchio", status=WorkOrder.STATUS_DONE, closed_at=timezone.now() - timedelta(days=500))
        scheda = self.client.get(_sezione(self.f, "manutenzione"))
        assets = self.client.get(reverse("assets:maintenance_supplier_detail", args=[self.f.pk]))
        self.assertEqual(scheda.status_code, 200)
        self.assertEqual(len(scheda.context["r"].open_wos), assets.context["open_total"])
        self.assertEqual(len(scheda.context["r"].closed_12m), assets.context["closed_12m"])
        self.assertEqual(scheda.context["r"].costo_12m, assets.context["costo_12m"])
        self.assertEqual(len(scheda.context["r"].open_wos), 1)
        self.assertEqual(len(scheda.context["r"].closed_12m), 1)
        self.assertContains(scheda, "Aperto uno")

    def test_odl_di_altra_ditta_non_si_vede(self):
        altra = Fornitore.objects.create(ragione_sociale="Altra Srl")
        WorkOrder.objects.create(asset=self.asset, supplier=altra, title="Non mio")
        self.assertEqual(rapporto_ditta(self.f).workorders, [])

    def test_ventinove_febbraio(self):
        self.assertEqual(un_anno_prima(date(2028, 2, 29)), date(2027, 2, 28))

    def test_da_guardare(self):
        self._odl(title="Aperto uno")
        AssistanceContract.objects.create(
            supplier=self.f, title="In scadenza", end_date=timezone.localdate() + timedelta(days=5),
        )
        r = self.client.get(reverse("fornitori:index"))
        testi = [v["testo"] for v in r.context["da_guardare"]]
        self.assertTrue(any("ordini di lavoro aperti" in t for t in testi))
        self.assertTrue(any("contratti di assistenza" in t for t in testi))


class CopieMfcTests(TestCase):
    def setUp(self):
        self.client.force_login(_superuser())
        self.base = Fornitore.objects.create(ragione_sociale="BASE S.p.A.")
        self.altro = Fornitore.objects.create(ragione_sociale="Toner Esempio Srl")
        self.macchina = Macchina.objects.create(
            reparto="Uffici", matricola="SN-1", contratto="C1", fornitore=Macchina.Fornitore.BASE,
        )

    def _fattura(self, numero="F1", trimestre="2026-Q1", fornitore="BASE"):
        fattura = Fattura.objects.create(
            numero=numero, data=date(2026, 4, 2), fornitore=fornitore, trimestre=trimestre,
            periodo_al=date(2026, 3, 31),
        )
        RigaFattura.objects.create(fattura=fattura, contratto="C1", a4_bn=100)
        return fattura

    def test_riconosciuto_dal_nome_senza_abbinamento(self):
        self.assertEqual(col.mappa_codici()["BASE"], self.base.pk)
        self.assertEqual(col.codici_del_fornitore(self.altro), [])
        r = self.client.get(reverse("fornitori:fornitore_detail", args=[self.base.pk]))
        self.assertContains(r, 'data-tab="tab-copie"')

    def test_scelta_a_mano_prevale_sul_nome(self):
        r = self.client.post(reverse("fornitori:fornitore_collega_contatori", args=[self.altro.pk]), {"codice": "BASE"})
        self.assertEqual(r.status_code, 302)
        self.assertIn("#tab-copie", r["Location"])
        self.assertEqual(col.mappa_codici()["BASE"], self.altro.pk)
        self.assertEqual(col.codici_del_fornitore(self.base), [])

    def test_togliere_il_collegamento_torna_al_nome(self):
        FornitoreContatori.objects.create(codice="BASE", fornitore=self.altro)
        self.client.post(reverse("fornitori:fornitore_collega_contatori", args=[self.altro.pk]),
                         {"codice": "BASE", "azione": "togli"})
        self.assertEqual(col.mappa_codici()["BASE"], self.base.pk)

    def test_codice_inesistente_non_salva(self):
        self.client.post(reverse("fornitori:fornitore_collega_contatori", args=[self.altro.pk]), {"codice": "XXX"})
        self.assertFalse(FornitoreContatori.objects.exists())

    def test_nome_ambiguo_non_collega(self):
        Fornitore.objects.create(ragione_sociale="Base Srl")
        self.assertIsNone(col.mappa_codici()["BASE"])

    def test_solo_le_fatture_della_ditta_e_stesso_esito_della_riconciliazione(self):
        from contatori import services as cs

        mia = self._fattura()
        altra = self._fattura(numero="F2", fornitore="COPYLAB")
        LetturaContatori.objects.create(
            macchina=self.macchina, trimestre="2026-Q1", data=date(2026, 4, 1), a4_bn=80,
        )
        dati = col.dati_copie(self.base)
        self.assertEqual([f.pk for f in dati["fatture"]], [mia.pk])
        self.assertNotIn(altra.pk, [f.pk for f in dati["fatture"]])
        gruppo = next(g for g in cs.riconcilia("2026-Q1")[1]["gruppi"] if g["fattura"].pk == mia.pk)
        self.assertEqual(dati["fatture"][0].esito_livello, gruppo["livello"])
        self.assertEqual(dati["fatture"][0].esito_livello, "danger")
        self.assertEqual(dati["fatture"][0].copie_in_eccesso, 20)
        self.assertEqual(dati["da_controllare"], 1)

    def test_trimestre_con_letture_senza_fattura_della_ditta(self):
        self._fattura(trimestre="2025-Q1")
        LetturaContatori.objects.create(macchina=self.macchina, trimestre="2025-Q2", data=date(2025, 7, 1))
        self.assertEqual(col.dati_copie(self.base)["scoperti"], ["2025-Q2"])

    def test_sezione_e_link_dalle_fatture(self):
        self._fattura()
        r = self.client.get(_sezione(self.base, "copie"))
        self.assertContains(r, "F1")
        self.assertContains(r, "SN-1")
        r = self.client.get(reverse("contatori:fatture"))
        self.assertContains(r, reverse("fornitori:fornitore_detail", args=[self.base.pk]))


def _riga_gp(nome="Mario", cognome="Rossi", ingressi=3, minuti=90, dentro=0):
    return gp.TecnicoDitta(
        nome=f"{nome} {cognome}", ingressi=ingressi, minuti=minuti,
        primo=datetime(2026, 1, 1, 8), ultimo=datetime(2026, 3, 1, 8), dentro=bool(dentro),
    )


class TecniciTests(TestCase):
    def setUp(self):
        self.client.force_login(_superuser())
        self.f = Fornitore.objects.create(ragione_sociale="Tecnici Esempio Srl")
        self.asset = Asset.objects.create(name="Pressa di prova", asset_tag="TST-2")
        self.odl = WorkOrder.objects.create(asset=self.asset, supplier=self.f, title="Riparazione")

    def _link(self, nome="ROSSI Mario", visita=11):
        return IngressoIntervento.objects.create(
            visita_gp_id=visita, work_order=self.odl, fornitore=self.f, tecnico_nome=nome,
            ingresso=timezone.make_aware(datetime(2026, 2, 1, 9)), uscita=timezone.make_aware(datetime(2026, 2, 1, 11)),
        )

    def test_senza_guestportal_restano_gli_ingressi_collegati(self):
        self._link()
        with patch.object(gp, "db_configurato", return_value=False):
            dati = col.dati_tecnici(self.f)
            r = self.client.get(_sezione(self.f, "tecnici"))
        self.assertFalse(dati["configurato"])
        self.assertEqual([t.nome for t in dati["da_registrare"]], ["ROSSI Mario"])
        self.assertContains(r, "ROSSI Mario")
        self.assertContains(r, "non è collegato")

    def test_guestportal_che_non_risponde_non_rompe(self):
        self._link()
        with patch.object(gp, "db_configurato", return_value=True), \
                patch.object(gp, "ditte_guestportal", side_effect=gp.GuestPortalNonRaggiungibile("giù")):
            r = self.client.get(_sezione(self.f, "tecnici"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "non risponde")
        self.assertContains(r, "ROSSI Mario")

    def test_stessa_persona_unita_tra_guestportal_e_collegamenti(self):
        self._link()
        with patch.object(gp, "db_configurato", return_value=True), \
                patch.object(gp, "ditte_guestportal", return_value=[]), \
                patch.object(gp, "tecnici_ditta", return_value=([_riga_gp(), _riga_gp(ingressi=1, minuti=10, dentro=1)], False)), \
                patch.object(gp, "ingressi_ditta", return_value=[]):
            dati = col.dati_tecnici(self.f)
        self.assertEqual(len(dati["da_registrare"]), 1)
        t = dati["da_registrare"][0]
        self.assertEqual((t.ingressi, t.minuti, t.dentro, len(t.interventi)), (4, 100, True, 1))
        self.assertEqual(t.ultimo, datetime(2026, 3, 1, 8))
        self.assertEqual(dati["n_dentro"], 1)

    def test_query_tecnici_esclude_anonimizzati_e_segnala_il_taglio(self):
        righe = [{"FirstName": "A", "LastName": str(i), "Ingressi": 1, "Minuti": None, "Dentro": 0} for i in range(3)]
        with patch.object(gp, "_esegui", return_value=righe) as esegui:
            elenco, troncato = gp.tecnici_ditta(ditte_gp=[5], nomi=["Ditta"], limite=2)
        sql, params = esegui.call_args[0]
        self.assertIn("g.IsAnonymized = 0", sql)
        self.assertEqual(params[0], 5)
        self.assertEqual(params[-1], 3)
        self.assertTrue(troncato)
        self.assertEqual(len(elenco), 2)
        self.assertEqual(elenco[0].minuti, 0)

    def test_ditta_senza_riferimenti_non_interroga(self):
        with patch.object(gp, "_esegui") as esegui:
            self.assertEqual(gp.tecnici_ditta(ditte_gp=[], nomi=[]), ([], False))
        esegui.assert_not_called()

    def test_tecnici_di_altra_ditta_non_si_vedono(self):
        self._link()
        altra = Fornitore.objects.create(ragione_sociale="Altra Srl")
        self.assertEqual(col.collegamenti_del_fornitore(altra).count(), 0)


class ScadenzeTests(TestCase):
    def setUp(self):
        self.client.force_login(_superuser())
        self.f = Fornitore.objects.create(ragione_sociale="Scadenze Esempio Srl")

    def test_contratto_scaduto_e_in_scadenza_ordinati(self):
        oggi = timezone.localdate()
        AssistanceContract.objects.create(supplier=self.f, title="Futuro", end_date=oggi + timedelta(days=200))
        AssistanceContract.objects.create(supplier=self.f, title="Vicino", end_date=oggi + timedelta(days=30))
        AssistanceContract.objects.create(supplier=self.f, title="Passato", end_date=oggi - timedelta(days=1))
        r = self.client.get(_sezione(self.f, "scadenze"))
        self.assertEqual([v["cosa"] for v in r.context["voci"]], ["Passato", "Vicino", "Futuro"])
        self.assertEqual([v["stato"] for v in r.context["voci"]], ["scaduta", "in_scadenza", "ok"])
        self.assertEqual(r.context["n_scadute"], 1)


class ElencoTests(TestCase):
    def setUp(self):
        self.client.force_login(_superuser())
        self.in_sede = Fornitore.objects.create(ragione_sociale="In Sede Srl", accede_in_sede=True)
        self.normale = Fornitore.objects.create(ragione_sociale="Solo Materiali Srl")
        self.spento = Fornitore.objects.create(ragione_sociale="Spento Srl", is_active=False)
        self.url = reverse("fornitori:fornitori_list")

    def test_filtro_documenti_coerente_con_da_guardare(self):
        r = self.client.get(self.url, {"requisiti": "non_in_regola"})
        self.assertEqual([f.pk for f in r.context["page_obj"]], [self.in_sede.pk])
        guarda = next(v for v in self.client.get(reverse("fornitori:index")).context["da_guardare"]
                      if "non in regola" in v["testo"])
        self.assertEqual(guarda["n"], r.context["page_obj"].paginator.count)

    def test_solo_attivi_tolto_mostra_tutti(self):
        self.assertEqual(self.client.get(self.url).context["page_obj"].paginator.count, 2)
        self.assertEqual(self.client.get(self.url, {"q": ""}).context["page_obj"].paginator.count, 3)
        self.assertEqual(self.client.get(self.url, {"q": "", "attivi": "1"}).context["page_obj"].paginator.count, 2)

    def test_csv_con_i_filtri(self):
        r = self.client.get(self.url, {"formato": "csv", "requisiti": "non_in_regola"})
        self.assertEqual(r.status_code, 200)
        testo = r.content.decode("utf-8-sig")
        self.assertIn("In Sede Srl", testo)
        self.assertNotIn("Solo Materiali", testo)
        self.assertIn("Documenti non in regola", testo)
