"""Scelta multipla nelle regole e ambito «propri / team / tutti»."""
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import AccessGroup, Profile

from . import visibilita as vis
from .models import CategoriaScadenza, RegolaVisibilita, ScadenzaGenerica, VoceConfig
from .tests import OGGI, _ident, _item, _utente


def _voce(titolo, **extra):
    v = _item(elemento=titolo, titolo=titolo)
    v.extra = extra
    return v


class AmbitoTests(TestCase):
    def setUp(self):
        self.ident = _ident(legacy=10)
        self.ident._team = frozenset({20})
        p = patch.object(vis, "identita_di", return_value=self.ident)
        p.start()
        self.addCleanup(p.stop)
        self.mia = _voce("Mia", legacy_user_id=10)
        self.del_team = _voce("Team", legacy_user_id=20)
        self.altrui = _voce("Altrui", legacy_user_id=30)
        self.senza = _voce("Senza")
        self.tutte = [self.mia, self.del_team, self.altrui, self.senza]

    def _titoli(self, modulo=(), sistema=()):
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=True), method="GET")
        esito = vis.applica(request, list(modulo), raccogli_sistema=lambda fonti: list(sistema))
        return sorted(v.titolo for v in esito)

    def _regola(self, ambito, chiave="hr"):
        return RegolaVisibilita.objects.create(chiave=chiave, persona_legacy_id=10, ambito=ambito)

    def test_tutti_concede_ogni_voce_anche_senza_persona(self):
        self._regola("tutti")
        self.assertEqual(self._titoli(sistema=self.tutte), ["Altrui", "Mia", "Senza", "Team"])

    def test_propri_solo_le_sue(self):
        self._regola("propri")
        self.assertEqual(self._titoli(sistema=self.tutte), ["Mia"])

    def test_team_le_sue_e_quelle_del_team(self):
        self._regola("team")
        self.assertEqual(self._titoli(sistema=self.tutte), ["Mia", "Team"])

    def test_due_regole_vale_la_piu_ampia(self):
        self._regola("propri", chiave="hr")
        self._regola("tutti", chiave="hr|qualifica|altrui")
        self.assertEqual(self._titoli(sistema=self.tutte), ["Altrui", "Mia"])

    def test_modalita_modulo_non_toglie_le_voci_del_modulo(self):
        self._regola("propri")
        self.assertEqual(self._titoli(modulo=[self.altrui]), ["Altrui"])

    def test_solo_regole_limita_anche_le_voci_del_modulo(self):
        VoceConfig.objects.create(chiave="hr", modalita=VoceConfig.MODALITA_REGOLE)
        self._regola("propri")
        self.assertEqual(self._titoli(modulo=[self.mia, self.altrui, self.senza]), ["Mia"])

    def test_senza_identita_legacy_propri_non_concede(self):
        self.ident.legacy_user_id = None
        gruppo = AccessGroup.objects.create(code="sz_a", label="A")
        RegolaVisibilita.objects.create(chiave="hr", ruolo_portale=gruppo, ambito="propri")
        self.ident.ruoli_portale = frozenset({gruppo.pk})
        self.assertEqual(self._titoli(sistema=self.tutte), [])

    def test_proprietari_da_tutte_le_chiavi_degli_extra(self):
        from assets.models import Asset

        user = get_user_model().objects.create_user("sz.pr", "sz.pr@example.com", "pwd12345")
        Profile.objects.update_or_create(user=user, defaults={"legacy_user_id": 41})
        asset = Asset.objects.create(name="Pc", asset_tag="SZ-1", assigned_legacy_user_id=43)
        voci = [_voce("U", utente_id=user.pk), _voce("R", responsabile_id=user.pk), _voce("A", legacy_id=5),
                _voce("S", asset_id=asset.pk), _voce("L", legacy_user_id=44), _voce("N")]
        with patch.object(vis, "_legacy_da_anagrafiche", return_value={5: 42}):
            esito = vis.proprietari_voci(voci)
        self.assertEqual([sorted(esito[id(v)]) for v in voci], [[41], [41], [42], [43], [44], []])

    def test_errore_di_lettura_lascia_senza_proprietario(self):
        self._regola("propri")
        with patch.object(vis, "_legacy_da_utenti", side_effect=RuntimeError("boom")):
            self.assertEqual(self._titoli(sistema=[_voce("X", utente_id=1)]), [])


class AggiuntaMultiplaTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_superuser("sz.adm", "sz.adm@example.com", "pwd12345"))
        self.a = AccessGroup.objects.create(code="sz_a", label="Ruolo A")
        self.b = AccessGroup.objects.create(code="sz_b", label="Ruolo B")
        self.url = reverse("scadenzario:gestione_regola_aggiungi")

    def _post(self, **dati):
        dati.setdefault("chiave", "asset")
        dati.setdefault("livello", "VEDE")
        with patch("scadenzario.forms.persone_choices", return_value=[(42, "Bianchi Anna")]) as persone:
            risposta = self.client.post(self.url, dati)
        self.assertLessEqual(persone.call_count, 1)
        return risposta

    def test_piu_destinatari_insieme_con_lo_stesso_ambito(self):
        scelte = [f"ruolo_portale:{self.a.pk}", f"ruolo_portale:{self.b.pk}", "persona:42"]
        self.assertEqual(self._post(chi=scelte, ambito="team").status_code, 302)
        regole = RegolaVisibilita.objects.all()
        self.assertEqual(regole.count(), 3)
        self.assertEqual({r.ambito for r in regole}, {"team"})
        self.assertEqual(regole.get(persona_legacy_id=42).persona_nome, "Bianchi Anna")

    def test_una_scelta_non_valida_non_salva_niente(self):
        self._post(chi=[f"ruolo_portale:{self.a.pk}", "ruolo_portale:999999"])
        self.assertFalse(RegolaVisibilita.objects.exists())

    def test_nessuna_scelta_non_salva(self):
        self.assertEqual(self._post().status_code, 302)
        self.assertFalse(RegolaVisibilita.objects.exists())

    def test_ambito_non_valido_non_salva(self):
        self._post(chi=[f"ruolo_portale:{self.a.pk}"], ambito="reparto")
        self.assertFalse(RegolaVisibilita.objects.exists())

    def test_destinatario_gia_presente_aggiorna_senza_doppioni(self):
        RegolaVisibilita.objects.create(chiave="asset", ruolo_portale=self.a)
        self._post(chi=[f"ruolo_portale:{self.a.pk}"], ambito="propri")
        self.assertEqual(RegolaVisibilita.objects.get().ambito, "propri")

    def test_gestione_e_pannello_sempre_tutti(self):
        self._post(chi=[f"ruolo_portale:{self.a.pk}"], chiave="generiche", livello="GESTISCE", ambito="propri")
        self._post(chi=[f"ruolo_portale:{self.a.pk}"], chiave=vis.CHIAVE_PANNELLO, ambito="propri")
        self.assertEqual({r.ambito for r in RegolaVisibilita.objects.all()}, {"tutti"})

    def test_modifica_regola_esistente(self):
        regola = RegolaVisibilita.objects.create(chiave="generiche", ruolo_portale=self.a)
        url = reverse("scadenzario:gestione_regola_modifica", args=[regola.pk])
        self.client.post(url, {"ambito": "team"})
        regola.refresh_from_db()
        self.assertEqual(regola.ambito, "team")
        self.client.post(url, {"livello": "GESTISCE", "ambito": "propri"})
        regola.refresh_from_db()
        self.assertEqual((regola.livello, regola.ambito), ("GESTISCE", "tutti"))
        self.client.post(url, {"livello": "VEDE", "ambito": "reparto"})
        regola.refresh_from_db()
        self.assertEqual(regola.livello, "GESTISCE")

    def test_modifica_e_aggiunta_negate_a_chi_non_gestisce(self):
        regola = RegolaVisibilita.objects.create(chiave="asset", ruolo_portale=self.a)
        self.client.force_login(_utente("sz.no"))
        modifica = reverse("scadenzario:gestione_regola_modifica", args=[regola.pk])
        with patch("scadenzario.views.puo_gestire_pannello", return_value=False):
            self.assertEqual(self.client.post(modifica, {"ambito": "propri"}).status_code, 403)
            self.assertEqual(self.client.post(self.url, {"chiave": "asset", "chi": f"ruolo_portale:{self.b.pk}"}).status_code, 403)
        regola.refresh_from_db()
        self.assertEqual(regola.ambito, "tutti")

    def test_pagina_mostra_caselle_e_ambito_senza_chi_ha_gia_la_regola(self):
        RegolaVisibilita.objects.create(chiave="asset", ruolo_portale=self.a, ambito="team")
        with patch("dashboard.scadenze_providers.collect_sistema", return_value=[]):
            r = self.client.get(reverse("scadenzario:gestione") + "?chiave=asset")
        self.assertContains(r, 'type="checkbox" name="chi"')
        self.assertContains(r, f'value="ruolo_portale:{self.b.pk}"')
        self.assertNotContains(r, f'value="ruolo_portale:{self.a.pk}"')
        self.assertContains(r, '<option value="team" selected>')
        self.assertContains(r, "Quali scadenze")

    def test_pannello_senza_ambito(self):
        with patch("dashboard.scadenze_providers.collect_sistema", return_value=[]):
            r = self.client.get(reverse("scadenzario:gestione") + "?chiave=" + vis.CHIAVE_PANNELLO)
        self.assertContains(r, 'name="chi"')
        self.assertNotContains(r, "Quali scadenze")


class GenericheAmbitoTests(TestCase):
    def setUp(self):
        self.cat = CategoriaScadenza.objects.create(nome="Verifiche")
        self.capo = _utente("sz.capo")
        self.collega = _utente("sz.collega")
        self.altro = _utente("sz.altro")
        for user, legacy in ((self.capo, 10), (self.collega, 20), (self.altro, 30)):
            Profile.objects.update_or_create(user=user, defaults={"legacy_user_id": legacy})
        self.sua = ScadenzaGenerica.objects.create(categoria=self.cat, titolo="Della persona", data_scadenza=OGGI, responsabile=self.capo)
        self.team = ScadenzaGenerica.objects.create(categoria=self.cat, titolo="Del collega", data_scadenza=OGGI, responsabile=self.collega)
        self.fuori = ScadenzaGenerica.objects.create(categoria=self.cat, titolo="Di un altro", data_scadenza=OGGI, responsabile=self.altro)
        self.nessuno = ScadenzaGenerica.objects.create(categoria=self.cat, titolo="Di nessuno", data_scadenza=OGGI)
        self.client.force_login(self.capo)

    def _ident(self):
        ident = _ident(legacy=10)
        ident._team = frozenset({20})
        return ident

    def test_team_vede_solo_i_responsabili_del_team(self):
        RegolaVisibilita.objects.create(chiave=f"generiche|cat-{self.cat.pk}", persona_legacy_id=10, ambito="team")
        with patch("scadenzario.visibilita.identita_di", return_value=self._ident()):
            elenco = self.client.get(reverse("scadenzario:elenco"))
            self.assertContains(elenco, "Del collega")
            self.assertContains(elenco, "Della persona")
            self.assertNotContains(elenco, "Di un altro")
            self.assertNotContains(elenco, "Di nessuno")
            dettaglio = lambda s: self.client.get(reverse("scadenzario:scadenza_dettaglio", args=[s.pk])).status_code
            self.assertEqual(dettaglio(self.team), 200)
            self.assertEqual(dettaglio(self.fuori), 403)
            self.assertEqual(dettaglio(self.nessuno), 403)

    def test_ambito_limitato_non_apre_avvisi_ne_gestione(self):
        RegolaVisibilita.objects.create(chiave=f"generiche|cat-{self.cat.pk}", persona_legacy_id=10, ambito="propri")
        with patch("scadenzario.visibilita.identita_di", return_value=self._ident()):
            self.assertEqual(self.client.get(reverse("scadenzario:avvisi")).status_code, 403)
            self.assertEqual(self.client.get(reverse("scadenzario:scadenza_modifica", args=[self.sua.pk])).status_code, 403)
