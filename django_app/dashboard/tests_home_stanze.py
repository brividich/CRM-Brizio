"""Home a stanze: scaffale self-help, organizzazione della sicurezza, guida in-app."""
from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.hub_bacheca import visible_bacheca
from core.models import HubLink, HubLinkCategory
from dashboard import views_home_portale as hp


def _admin_request():
    return SimpleNamespace(
        user=SimpleNamespace(is_superuser=True, get_username=lambda: "admin", first_name="", email=""),
        legacy_user=SimpleNamespace(id=1, ruolo="AMMINISTRAZIONE", ruolo_id=1, nome="Admin"),
    )


class SiglaCopertinaTests(TestCase):
    def test_sigla_impostata_vince(self):
        self.assertEqual(HubLink(title="Collegarsi tramite VPN", sigla="VPN").sigla_copertina, "VPN")

    def test_sigla_dalle_iniziali_del_titolo(self):
        self.assertEqual(HubLink(title="Come creare una password sicura").sigla_copertina, "CCU")

    def test_sigla_da_una_parola_sola(self):
        self.assertEqual(HubLink(title="Scorciatoie").sigla_copertina, "SCOR")

    def test_titolo_vuoto(self):
        self.assertEqual(HubLink(title="").sigla_copertina, "?")


class SezioniBachecaTests(TestCase):
    def setUp(self):
        self.doc = HubLinkCategory.objects.create(name="Modulistica", slug="modulistica")
        self.sh = HubLinkCategory.objects.create(
            name="IT e accessi", slug="it", sezione=HubLinkCategory.SEZIONE_SELF_HELP, colore="#123456"
        )
        HubLink.objects.create(category=self.doc, kind=HubLink.KIND_URL, title="Regolamento", url="https://e.local/r")
        self.vpn = HubLink.objects.create(
            category=self.sh, kind=HubLink.KIND_URL, title="Collegarsi tramite VPN", sigla="VPN", url="https://e.local/v"
        )

    def test_visible_bacheca_filtra_per_sezione(self):
        nomi = lambda gs: [g["category"].name for g in gs]  # noqa: E731
        self.assertEqual(nomi(visible_bacheca(1, is_admin=True, sezione="self_help")), ["IT e accessi"])
        self.assertEqual(nomi(visible_bacheca(1, is_admin=True, sezione="documenti")), ["Modulistica"])
        self.assertEqual(len(visible_bacheca(1, is_admin=True)), 2)

    def test_documenti_della_home_escludono_il_self_help(self):
        groups = hp._documenti_collegamenti(_admin_request(), sezione=HubLinkCategory.SEZIONE_DOCUMENTI)
        self.assertNotIn("IT e accessi", [g["name"] for g in groups])

    def test_scaffale_self_help(self):
        gruppi = hp._risorse_self_help(_admin_request())
        self.assertEqual(len(gruppi), 1)
        self.assertEqual(gruppi[0]["colore"], "#123456")
        voce = gruppi[0]["items"][0]
        self.assertEqual(voce["sigla"], "VPN")
        self.assertTrue(voce["is_new"])
        self.assertTrue(voce["open_in_new_tab"])

    def test_risorsa_vecchia_non_e_nuova(self):
        HubLink.objects.filter(pk=self.vpn.pk).update(
            created_at=timezone.now() - timedelta(days=hp.SELF_HELP_NUOVA_GIORNI + 1)
        )
        self.assertFalse(hp._risorse_self_help(_admin_request())[0]["items"][0]["is_new"])

    def test_colore_predefinito(self):
        HubLinkCategory.objects.filter(pk=self.sh.pk).update(colore="")
        self.assertEqual(hp._risorse_self_help(_admin_request())[0]["colore"], hp.SELF_HELP_COLORE_DEFAULT)


class AdminBachecaSezioneTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username="admin", password="x", email="a@a.it")
        self.client.force_login(self.admin)

    def _post(self, name, payload):
        return self.client.post(reverse(f"admin_portale:{name}"), data=json.dumps(payload),
                                content_type="application/json")

    def test_crea_categoria_self_help_con_colore(self):
        r = self._post("api_hub_category_create", {"name": "Guide IT", "sezione": "self_help", "colore": "#1F4F86"})
        self.assertEqual(r.status_code, 200)
        cat = HubLinkCategory.objects.get(name="Guide IT")
        self.assertEqual((cat.sezione, cat.colore), ("self_help", "#1f4f86"))

    def test_valori_non_validi_ripiegano_sui_predefiniti(self):
        self._post("api_hub_category_create", {"name": "Strana", "sezione": "boh", "colore": "red;x"})
        cat = HubLinkCategory.objects.get(name="Strana")
        self.assertEqual((cat.sezione, cat.colore), ("documenti", ""))

    def test_aggiorna_sezione(self):
        cat = HubLinkCategory.objects.create(name="Coll", slug="coll")
        self._post("api_hub_category_update", {"id": cat.id, "sezione": "self_help"})
        cat.refresh_from_db()
        self.assertEqual(cat.sezione, "self_help")

    def test_crea_voce_con_sigla(self):
        cat = HubLinkCategory.objects.create(name="Coll", slug="coll2")
        self._post("api_hub_link_create", {"category_id": cat.id, "kind": "url", "title": "Webmail",
                                           "url": "https://e.local/w", "sigla": "MAIL-LUNGHISSIMA"})
        self.assertEqual(HubLink.objects.get(title="Webmail").sigla, "MAIL-LUN")


class SicurezzaHomeTests(TestCase):
    """Le figure arrivano dai ruoli dell'ambito sicurezza; il preposto del proprio reparto va in testa."""

    def setUp(self):
        from anagrafica.models import AmbitoRuolo, DipendenteRuoloOperativo, RuoloOperativo

        self.ambito, _ = AmbitoRuolo.objects.get_or_create(nome="Sicurezza ISO 45001", defaults={"ordine": 30})
        rspp = RuoloOperativo.objects.create(nome="RSPP test", ambito=self.ambito, descrizione="Coordina il servizio.")
        prep = RuoloOperativo.objects.create(nome="Preposto test", ambito=self.ambito)
        coord = RuoloOperativo.objects.create(nome="Coordinatore emergenze test", ambito=self.ambito)
        RuoloOperativo.objects.create(nome="ASPP test", ambito=self.ambito)  # scoperto
        for ruolo, lid in ((rspp, 501), (prep, 502), (prep, 503), (coord, 504)):
            DipendenteRuoloOperativo.objects.create(ruolo=ruolo, legacy_anagrafica_id=lid)
        self.righe = [
            {"id": 501, "nome": "Giulia", "cognome": "Marchetti", "reparto": "HSE", "attivo": True,
             "email_notifica": "rspp@esempio.local"},
            {"id": 502, "nome": "Luca", "cognome": "Rinaldi", "reparto": "CNC", "attivo": True},
            {"id": 503, "nome": "Anna", "cognome": "Bianchi", "reparto": "Montaggio", "attivo": True},
            {"id": 504, "nome": "Roberto", "cognome": "Galli", "reparto": "Logistica", "attivo": True},
        ]

    def _build(self, reparto="CNC"):
        from dashboard import home_sicurezza

        with (
            patch("core.legacy_anagrafica.fetch_anagrafica_rows", return_value=self.righe),
            patch.object(home_sicurezza, "_reparto_utente", return_value=reparto),
        ):
            return home_sicurezza.build_sicurezza(SimpleNamespace(id=9))

    def test_figure_ordinate_e_posizione_scoperta(self):
        data = self._build()
        self.assertEqual(data["ambito"], self.ambito)
        nomi = [f["nome"] for f in data["figure"]]
        self.assertLess(nomi.index("RSPP test"), nomi.index("Preposto test"))
        aspp = next(f for f in data["figure"] if f["nome"] == "ASPP test")
        self.assertEqual(aspp["persone"], [])

    def test_il_preposto_del_proprio_reparto_va_in_testa(self):
        data = self._build("CNC")
        self.assertTrue(data["mie"][0]["mio"])
        self.assertIn("RINALDI", data["mie"][0]["nome"].upper())
        self.assertTrue(data["persone"][0]["mio"])
        altri = [p for p in data["persone"] if "BIANCHI" in p["nome"].upper()]
        self.assertFalse(altri[0]["mio"])

    def test_senza_reparto_nessun_preposto_evidenziato(self):
        data = self._build("")
        self.assertFalse(any(p["mio"] for p in data["persone"]))

    def test_coordinatore_emergenze_ed_email(self):
        data = self._build()
        self.assertIn("GALLI", data["emergenza"][0]["nome"].upper())
        rspp = next(p for p in data["persone"] if p["ruolo"] == "RSPP test")
        self.assertEqual(rspp["email"], "rspp@esempio.local")

    def test_ex_dipendente_non_compare(self):
        from anagrafica.models import DipendenteAnagraficaAziendale

        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=503, data_cessazione=timezone.localdate())
        data = self._build()
        self.assertFalse(any("BIANCHI" in p["nome"].upper() for p in data["persone"]))

    def test_senza_ambito_sicurezza_resta_vuoto(self):
        from anagrafica.models import AmbitoRuolo
        from dashboard.home_sicurezza import build_sicurezza

        AmbitoRuolo.objects.filter(nome__icontains="45001").update(is_active=False)
        AmbitoRuolo.objects.filter(nome__icontains="sicurezza").update(is_active=False)
        self.assertIsNone(build_sicurezza(None)["ambito"])


class HomeStanzeRenderTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username="adm", email="a@a.it", password="x")
        self.client.force_login(self.admin)

    def test_home_mostra_le_quattro_stanze_e_la_guida(self):
        cat = HubLinkCategory.objects.create(name="IT e accessi", slug="it-r", sezione="self_help", colore="#1f4f86")
        HubLink.objects.create(category=cat, kind=HubLink.KIND_URL, title="Collegarsi tramite VPN",
                               sigla="VPN", url="https://e.local/v")
        resp = self.client.get(reverse("home_portale:index"))
        self.assertEqual(resp.status_code, 200)
        for testo in ("hs-room-oggi", "hs-room-sapere", "hs-room-persone", "hs-room-moduli",
                      "Risorse self-help", "Collegarsi tramite VPN", "Le mie attività"):
            self.assertContains(resp, testo)
        self.assertContains(resp, reverse("home_portale:guida"))

    def test_guida_mostra_tutte_le_sezioni(self):
        from django.utils.html import escape

        from dashboard.guida import SEZIONI

        resp = self.client.get(reverse("home_portale:guida"))
        self.assertEqual(resp.status_code, 200)
        for sez in SEZIONI:
            self.assertContains(resp, escape(sez["titolo"]))

    def test_guida_aperta_a_tutti_gli_utenti(self):
        from core.middleware import is_acl_shared_path

        self.assertTrue(is_acl_shared_path(reverse("home_portale:guida")))

    def test_guida_indicizzata_per_l_assistente(self):
        from ai_assistant import guide_portale

        sezioni = [s for s in guide_portale.sezioni() if s.slug == "home"]
        self.assertTrue(sezioni)
        self.assertTrue(all(s.url == reverse("home_portale:guida") for s in sezioni))
