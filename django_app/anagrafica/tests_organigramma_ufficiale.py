"""Organigrammi ufficiali: disegno, avvisi, riepilogo, pubblicazione e permessi."""
import json
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from anagrafica.models import (
    AmbitoRuolo,
    DipendenteAnagraficaAziendale,
    DipendenteRuoloOperativo,
    Mansione,
    OrganigrammaRevisione,
    OrganigrammaUfficiale,
    RuoloOperativo,
)
from anagrafica.services import organigramma_ufficiale as svc

User = get_user_model()


def _box(nid, **kw):
    n = {"id": nid, "tipo": "box", "x": 0, "y": 0, "w": 220, "h": 60}
    n.update(kw)
    return n


class NormalizzaTests(TestCase):
    def test_campi_ignoti_e_riferimenti_rotti_spariscono(self):
        d = svc.normalizza({"nodi": [
            _box("a", padre="zzz", gruppo="a", colore="red", stile="boh", extra="x", x="12.6"),
            {"id": "bad id!", "tipo": "box"},
        ]})
        self.assertEqual(len(d["nodi"]), 1)
        n = d["nodi"][0]
        self.assertIsNone(n["padre"])
        self.assertIsNone(n["gruppo"])
        self.assertEqual(n["colore"], svc.COLORE_DEFAULT)
        self.assertEqual(n["stile"], "bordo")
        self.assertEqual(n["x"], 13)
        self.assertNotIn("extra", n)

    def test_ciclo_nei_collegamenti_viene_spezzato(self):
        d = svc.normalizza({"nodi": [_box("a", padre="b"), _box("b", padre="a")]})
        padri = [n["padre"] for n in d["nodi"]]
        self.assertIn(None, padri)

    def test_gruppo_solo_verso_un_gruppo(self):
        d = svc.normalizza({"nodi": [
            {"id": "g1", "tipo": "gruppo", "titolo": "Team"}, _box("a", gruppo="g1"), _box("b", gruppo="a"),
        ]})
        per_id = {n["id"]: n for n in d["nodi"]}
        self.assertEqual(per_id["a"]["gruppo"], "g1")
        self.assertIsNone(per_id["b"]["gruppo"])

    def test_forma_sbagliata_solleva(self):
        with self.assertRaises(ValueError):
            svc.normalizza({"nodi": "no"})

    def test_campi_reparto_elenco_icona_e_foglio(self):
        d = svc.normalizza({
            "nodi": [
                _box("a", ruolo=3, ruoli_extra=[3, 4, "x", 4, 5], tutti_titolari=1, reparto="  Sales   dept ",
                     elenco_ruoli=[7, 8, 7], elenco_righe=["Rossi  Mario – IN1", ""], elenco_nascosti=[9, "no"],
                     icona="antincendio", tronco="sinistra"),
                _box("b", padre="a", lato=True, icona="boh", tronco="obliquo"),
                _box("c", padre="a", lato=True, staff=True),
                _box("d", lato=True),
            ],
            "foglio": {"stile": "documento", "titolo": "Organigramma", "piede": "Allegato C {rev}", "logo": False,
                       "ruoli_blu": False, "ignoto": 1},
        })
        a, b, c, e = d["nodi"]
        self.assertEqual(a["ruoli_extra"], [4, 5])  # il ruolo principale non si ripete
        self.assertEqual((a["reparto"], a["tutti_titolari"], a["icona"], a["tronco"]), ("Sales dept", True, "antincendio", "sinistra"))
        self.assertEqual((a["elenco_ruoli"], a["elenco_righe"], a["elenco_nascosti"]), ([7, 8], ["Rossi Mario – IN1", ""], [9]))
        self.assertEqual((b["lato"], b["icona"], b["tronco"]), (True, "", "centro"))
        self.assertEqual((c["staff"], c["lato"]), (True, False))  # staff vince su «di lato»
        self.assertFalse(e["lato"])  # senza superiore niente linea
        self.assertEqual(d["foglio"], {"stile": "documento", "titolo": "Organigramma", "sottotitolo": "", "intestazione": "",
                                       "azienda": "", "piede": "Allegato C {rev}", "logo": False, "ruoli_blu": False})
        self.assertEqual(svc.normalizza({"nodi": []})["foglio"]["stile"], "hub")

    def test_linee_spostate_a_mano(self):
        d = svc.normalizza({"nodi": [
            _box("a", tronco_x=-120.4), _box("b", padre="a", linea_y="30", bus_y=-5, entra_x=True),
            _box("c", padre="a", entra_x="abc", linea_y=99999),
        ]})
        a, b, c = d["nodi"]
        self.assertEqual(a["tronco_x"], -120)
        self.assertEqual((b["linea_y"], b["bus_y"], b["entra_x"]), (30, 0, None))
        self.assertEqual((c["entra_x"], c["linea_y"], c["bus_y"]), (None, 4000, None))
        # Spostare solo le linee è una modifica grafica, non di contenuto.
        dopo = svc.normalizza({"nodi": [_box("a", tronco_x=40), _box("b", padre="a", bus_y=24)]})
        prima = svc.normalizza({"nodi": [_box("a"), _box("b", padre="a")]})
        self.assertEqual([r["tipo"] for r in svc.riepilogo(prima, dopo)], ["grafica"])

    def test_testo_piede(self):
        f = {"piede": "Azienda – Allegato C {rev} – Organigramma"}
        self.assertEqual(svc.testo_piede(f, 19, "X"), "Azienda – Allegato C Rev.19 – Organigramma")
        self.assertEqual(svc.testo_piede({"piede": "Allegato C"}, 2, "X"), "Allegato C – Rev.2")
        self.assertEqual(svc.testo_piede({}, None, "Org"), "Org – Bozza")


class AvvisiRiepilogoTests(TestCase):
    def setUp(self):
        self.ruolo = RuoloOperativo.objects.create(nome="Resp Prod T")
        self.altro = RuoloOperativo.objects.create(nome="Qualita T")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=11, ruolo=self.ruolo)

    def test_persona_cessata_e_ruolo_non_suo(self):
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=12, data_cessazione=date(2026, 10, 31))
        dati = svc.normalizza({"nodi": [
            _box("a", ruolo=self.ruolo.pk, persona=12),
            _box("b", ruolo=self.altro.pk, persona=11),
            _box("c", ruolo=self.ruolo.pk, persona=11),
        ]})
        testi = [a["testo"] for a in svc.avvisi(dati, svc.contesto(dati))]
        self.assertTrue(any("cessato il 31/10/2026" in t for t in testi))
        self.assertTrue(any("non ha il ruolo «Qualita T»" in t for t in testi))
        # Il ruolo giusto non genera avvisi (nei test manca la tabella legacy dei nomi).
        self.assertFalse(any(a["nodo"] == "c" and "non più in anagrafica" not in a["testo"]
                             for a in svc.avvisi(dati, svc.contesto(dati))))

    def test_ruoli_dell_ambito_non_disegnati(self):
        amb = AmbitoRuolo.objects.create(nome="Prod T", alimenta_scheda=True)
        org = OrganigrammaUfficiale.objects.create(nome="Org T", ambito=amb)
        testi = [a["testo"] for a in svc.avvisi(svc.vuoto(), svc.contesto(svc.vuoto()), org)]
        self.assertIn("«Resp Prod T» non è nel disegno (1 persona)", testi)
        self.assertFalse(any("Qualita T" in t for t in testi))  # nessuno lo ricopre

    def test_catalogo_porta_sigle_e_titolari_degli_elenchi(self):
        self.altro.sigla = "QT"
        self.altro.save()
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=21, ruolo=self.altro)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=22, ruolo=self.altro)
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=22, data_cessazione=date(2026, 1, 31))
        p = svc.pacchetto({"nodi": [_box("a", ruolo=self.ruolo.pk, persona=11, elenco_ruoli=[self.altro.pk])]})
        r = p["cat"]["ruoli"][str(self.altro.pk)]
        self.assertEqual((r["sigla"], r["titolari"]), ("QT", [21]))  # il cessato non compare
        self.assertIn("21", p["cat"]["persone"])
        self.assertEqual(p["dati"]["foglio"]["stile"], "hub")

    def test_ruoli_negli_elenchi_contano_come_disegnati(self):
        amb = AmbitoRuolo.objects.create(nome="Prod T2", alimenta_scheda=True)
        org = OrganigrammaUfficiale.objects.create(nome="Org T2", ambito=amb)
        dati = svc.normalizza({"nodi": [_box("a", elenco_ruoli=[self.ruolo.pk])]})
        testi = [a["testo"] for a in svc.avvisi(dati, svc.contesto(dati), org)]
        self.assertFalse(any("Resp Prod T" in t for t in testi))

    def test_riepilogo_segnala_elenco_e_foglio(self):
        prima = svc.normalizza({"nodi": [_box("a", titolo="Ufficio")]})
        dopo = svc.normalizza({"nodi": [_box("a", titolo="Ufficio", elenco_ruoli=[self.ruolo.pk])],
                               "foglio": {"stile": "documento"}})
        righe = svc.riepilogo(prima, dopo)
        self.assertEqual([r["tipo"] for r in righe], ["modificato", "grafica"])
        self.assertEqual(righe[1]["titolo"], "Foglio: stile")
        self.assertEqual(righe[1]["dettaglio"], "stile Documento")

    def test_etichetta_ruolo_senza_persona_conta_i_titolari(self):
        dati = svc.normalizza({"nodi": [_box("a", ruolo=self.ruolo.pk), _box("b", ruolo=self.altro.pk)]})
        ctx = svc.contesto(dati)
        self.assertEqual(svc.etichetta(dati["nodi"][0], ctx)["sotto"], "1 persona")
        self.assertEqual(svc.etichetta(dati["nodi"][1], ctx)["sotto"], "Posizione scoperta")

    def test_riepilogo_aggiunto_tolto_spostato_rinominato_grafica(self):
        m = Mansione.objects.create(nome="Operatore CNC T")
        prima = svc.normalizza({"nodi": [
            _box("a", ruolo=self.ruolo.pk), _box("b", titolo="Vecchio"), _box("c", mansione=m.pk, padre="a"),
            {"id": "g1", "tipo": "gruppo", "titolo": "Qualità"}, _box("d", titolo="Fisso"),
        ]})
        dopo = svc.normalizza({"nodi": [
            _box("a", ruolo=self.ruolo.pk), _box("c", mansione=m.pk, padre=None),
            {"id": "g1", "tipo": "gruppo", "titolo": "Controllo qualità"}, _box("d", titolo="Fisso", x=40),
            _box("e", titolo="Nuovo", padre="a"),
        ]})
        righe = svc.riepilogo(prima, dopo)
        tipi = [r["tipo"] for r in righe]
        self.assertEqual(tipi, ["aggiunto", "spostato", "rinominato", "tolto", "grafica"])
        self.assertIn("sotto Resp Prod T", righe[0]["dettaglio"])
        self.assertEqual(righe[2]["titolo"], "«Qualità» → «Controllo qualità»")
        self.assertEqual(righe[4]["titolo"], "1 riquadro riposizionato")


class PubblicazioneTests(TestCase):
    def test_pubblica_crea_revisioni_numerate_e_chiude_la_bozza(self):
        org = OrganigrammaUfficiale.objects.create(nome="Org", bozza={"nodi": [_box("a", titolo="X")]})
        rev = svc.pubblica(org, nota="prima", approvato_da="Direzione", data_emissione=date(2026, 11, 26), user=None)
        org.refresh_from_db()
        self.assertEqual(rev.numero, 1)
        self.assertIsNone(org.bozza)
        org.bozza = {"nodi": [_box("a", titolo="Y")]}
        org.save()
        self.assertEqual(svc.pubblica(org, nota="", approvato_da="", data_emissione=date.today(), user=None).numero, 2)
        self.assertEqual(org.revisione_in_vigore().numero, 2)

    def test_disegno_vuoto_non_si_pubblica(self):
        org = OrganigrammaUfficiale.objects.create(nome="Vuoto", bozza=svc.vuoto())
        with self.assertRaises(ValueError):
            svc.pubblica(org, nota="", approvato_da="", data_emissione=date.today(), user=None)

    def test_non_tocca_ruoli_ne_assegnazioni(self):
        capo = RuoloOperativo.objects.create(nome="Capo T")
        sub = RuoloOperativo.objects.create(nome="Sub T")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=5, ruolo=sub)
        org = OrganigrammaUfficiale.objects.create(nome="Org", bozza={"nodi": [
            _box("a", ruolo=capo.pk), _box("b", ruolo=sub.pk, persona=5, padre="a")]})
        svc.pubblica(org, nota="", approvato_da="", data_emissione=date.today(), user=None)
        sub.refresh_from_db()
        self.assertIsNone(sub.riporta_a_id)
        self.assertEqual(DipendenteRuoloOperativo.objects.count(), 1)


class VisteTests(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("su-ouf", "su-ouf@test.local", "x")
        self.client.force_login(self.su)
        from core.models import UserOnboarding

        UserOnboarding.objects.update_or_create(user=self.su, defaults={"completed": True})

    def test_flusso_crea_disegna_salva_riepilogo_pubblica(self):
        # Pubblicazione diretta: firma su portale spenta (il flusso con le firme sta in tests_organigramma_firma).
        from timbri.models import ImpostazioneFirma

        ImpostazioneFirma.objects.create(tipo="organigramma_ufficiale", attiva=False)
        r = self.client.post(reverse("anagrafica:organigramma_ufficiale_nuovo"), {"nome": "Aziendale"})
        org = OrganigrammaUfficiale.objects.get(nome="Aziendale")
        self.assertRedirects(r, reverse("anagrafica:organigramma_ufficiale_disegna", args=[org.pk]),
                             fetch_redirect_response=False)
        r = self.client.get(reverse("anagrafica:organigramma_ufficiale_disegna", args=[org.pk]))
        self.assertContains(r, 'id="oudStatoJson"')
        self.assertContains(r, "data-no-search")

        url = reverse("anagrafica:organigramma_ufficiale_bozza", args=[org.pk])
        r = self.client.post(url, json.dumps({"disegno": {"nodi": [_box("a", titolo="Direzione")]}}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(r.json()["n_modifiche"], 1)

        r = self.client.get(reverse("anagrafica:organigramma_ufficiale_riepilogo", args=[org.pk]))
        self.assertEqual([x["tipo"] for x in r.json()["righe"]], ["aggiunto"])

        r = self.client.post(reverse("anagrafica:organigramma_ufficiale_pubblica", args=[org.pk]),
                             {"nota": "Prima emissione", "approvato_da": "Direzione", "data_emissione": "2026-11-26"})
        self.assertRedirects(r, reverse("anagrafica:organigramma_ufficiale_vedi", args=[org.pk]),
                             fetch_redirect_response=False)
        rev = OrganigrammaRevisione.objects.get(organigramma=org)
        self.assertEqual((rev.numero, rev.approvato_da), (1, "Direzione"))

        r = self.client.get(reverse("anagrafica:organigramma_ufficiale_vedi", args=[org.pk]))
        self.assertContains(r, "Direzione")
        self.assertContains(r, "Storico revisioni")
        r = self.client.get(reverse("anagrafica:organigramma_ufficiale_stampa", args=[org.pk]) + "?formato=A4")
        self.assertContains(r, "size:A4 landscape")
        self.assertContains(r, "Emessa il 26/11/2026")
        self.assertContains(r, "Aziendale – Rev.1")
        r = self.client.get(reverse("anagrafica:organigramma_ufficiale"))
        self.assertContains(r, "Aziendale")
        self.assertContains(r, "📐 Ufficiale")

    def test_stampa_piu_organigrammi_in_un_pdf(self):
        a = OrganigrammaUfficiale.objects.create(nome="Aziendale T")
        b = OrganigrammaUfficiale.objects.create(nome="Sicurezza T")
        c = OrganigrammaUfficiale.objects.create(nome="Mai pubblicato T", bozza={"nodi": [_box("x", titolo="X")]})
        for org, stile in ((a, "documento"), (b, "hub")):
            OrganigrammaRevisione.objects.create(
                organigramma=org, numero=1, data_emissione=date(2026, 11, 26),
                dati=svc.normalizza({"nodi": [_box("x", titolo="Direzione")],
                                     "foglio": {"stile": stile, "piede": "Allegato C {rev} – Organigramma"}}))
        r = self.client.get(reverse("anagrafica:organigramma_ufficiale_stampa", args=[a.pk]) + f"?con={b.pk},{c.pk},abc")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'class="foglio', count=2)  # il mai pubblicato resta fuori
        self.assertContains(r, "size:A4 portrait")  # stile Documento: A4 verticale di partenza
        self.assertContains(r, "Allegato C Rev.1 – Organigramma", count=2)
        self.assertContains(r, "tp-doc")
        self.assertContains(r, "tp-hub")
        r = self.client.get(reverse("anagrafica:organigramma_ufficiale"))
        self.assertContains(r, "Stampa insieme")
        self.assertContains(r, "ouf-mount")

    def test_tela_ha_stili_foglio_e_pannello_elenco(self):
        org = OrganigrammaUfficiale.objects.create(nome="T", bozza=svc.vuoto())
        r = self.client.get(reverse("anagrafica:organigramma_ufficiale_disegna", args=[org.pk]))
        for testo in ('data-act="stile-documento"', 'id="oudFoglio"', "pannelloElenco", "window.OUF"):
            self.assertContains(r, testo)

    def test_bozza_rifiuta_json_sbagliato(self):
        org = OrganigrammaUfficiale.objects.create(nome="X")
        url = reverse("anagrafica:organigramma_ufficiale_bozza", args=[org.pk])
        r = self.client.post(url, "non json", content_type="application/json")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])


class PermessiTests(TestCase):
    def setUp(self):
        self.utente = User.objects.create_user("semplice-ouf", "s@test.local", "x")
        self.org = OrganigrammaUfficiale.objects.create(nome="Org P")

    def test_api_risponde_json_403_a_chi_non_puo_disegnare(self):
        from django.test import RequestFactory
        from django.contrib.sessions.backends.db import SessionStore

        from anagrafica import views_organigramma_ufficiale as v

        req = RequestFactory().post("/x/api/bozza/", "{}", content_type="application/json")
        req.user = self.utente
        req.session = SessionStore()
        r = v.organigramma_ufficiale_bozza(req, self.org.pk)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(json.loads(r.content)["ok"])

    def test_api_risponde_json_401_senza_login(self):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory

        from anagrafica import views_organigramma_ufficiale as v

        req = RequestFactory().get("/x/api/riepilogo/")
        req.user = AnonymousUser()
        r = v.organigramma_ufficiale_riepilogo(req, self.org.pk)
        self.assertEqual(r.status_code, 401)

    def test_binding_acl_per_tutte_le_rotte(self):
        from core.models import RoutePermissionBinding

        rotte = [
            "organigramma_ufficiale", "organigramma_ufficiale_vedi", "organigramma_ufficiale_stampa",
            "organigramma_ufficiale_nuovo", "organigramma_ufficiale_disegna", "organigramma_ufficiale_modifica",
            "organigramma_ufficiale_pubblica", "organigramma_ufficiale_scarta", "organigramma_ufficiale_bozza",
            "organigramma_ufficiale_riepilogo",
        ]
        import importlib

        from django.apps import apps

        mig = importlib.import_module("anagrafica.migrations.0256_organigramma_ufficiale")
        modello = RoutePermissionBinding.objects.filter(is_active=True).first()
        if modello is None:
            self.skipTest("nessun binding nel DB di prova da usare come modello")
        RoutePermissionBinding.objects.filter(route_name__in=[f"anagrafica:{r}" for r in rotte]).delete()
        for sorella in ("anagrafica:organigramma_diagramma", "anagrafica:ruolo_operativo_edit"):
            RoutePermissionBinding.objects.filter(route_name=sorella).delete()
            RoutePermissionBinding.objects.create(
                route_name=sorella, path_pattern="", match_strategy=modello.match_strategy,
                permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority, is_active=True,
            )
        mig.avanti(apps, None)
        presenti = set(RoutePermissionBinding.objects.filter(
            route_name__in=[f"anagrafica:{r}" for r in rotte]).values_list("route_name", flat=True))
        self.assertEqual(presenti, {f"anagrafica:{r}" for r in rotte})
        self.assertTrue(RoutePermissionBinding.objects.filter(
            route_name="anagrafica:organigramma_ufficiale_bozza", note__contains="ruolo_operativo_edit").exists())

        # 0266: le pagine della firma copiano vedi (firmare) e pubblica (inviare, impostare)
        mig2 = importlib.import_module("anagrafica.migrations.0266_org_ufficiale_firma_binding")
        mig2.avanti(apps, None)
        nuove = [r for rotte2 in mig2.COPIE.values() for r in rotte2]
        self.assertEqual(set(RoutePermissionBinding.objects.filter(route_name__in=nuove).values_list("route_name", flat=True)),
                         set(nuove))
        self.assertTrue(RoutePermissionBinding.objects.filter(
            route_name="anagrafica:organigramma_ufficiale_firma", note__contains="organigramma_ufficiale_vedi").exists())
