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
        self.assertContains(r, "Rev.1 del 26/11/2026")
        r = self.client.get(reverse("anagrafica:organigramma_ufficiale"))
        self.assertContains(r, "Aziendale")
        self.assertContains(r, "📐 Ufficiale")

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
