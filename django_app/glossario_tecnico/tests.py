"""Test B1 glossario tecnico: modelli, seed, import CSV, candidati (senza AI),
proposte AI con LLM mockato, ACL e coda di revisione. Solo dati sintetici."""

from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .acl_bootstrap import PERM_VIEW
from .chiave import normalizza_chiave
from .models import Termine, Variante
from .seed_data import TERMINI
from . import services

User = get_user_model()


def _termine(nome="lamatura di prova", categoria="lavorazione", **kw):
    return Termine.objects.create(termine=nome, categoria=categoria, definizione="Definizione sintetica.", **kw)


class ModelliTests(TestCase):
    def test_normalizzazione_chiave(self):
        self.assertEqual(normalizza_chiave("  Lamatùra   PROFONDA "), "lamatura profonda")
        self.assertEqual(normalizza_chiave("Planarità"), "planarita")
        self.assertEqual(normalizza_chiave("⌴"), "⌴")

    def test_variante_univoca_tra_termini(self):
        a = _termine("termine a")
        b = _termine("termine b")
        services.aggiungi_variante(a, "Spot Facex Sintetica", "traduzione", "en")
        self.assertEqual(a.varianti.get().chiave, "spot facex sintetica")
        with self.assertRaises(ValidationError) as ctx:
            services.aggiungi_variante(b, "spot  facex sintetica", "traduzione", "en")
        self.assertIn("termine a", str(ctx.exception))
        with self.assertRaises(ValidationError):
            services.aggiungi_variante(b, "   ", "sinonimo")
        with self.assertRaises(ValidationError):
            services.aggiungi_variante(b, "altro", "tipo_inventato")

    def test_termine_unico_per_categoria(self):
        _termine("passo sintetico", "filettatura")
        _termine("passo sintetico", "quotatura")  # stesso termine, categoria diversa: ammesso
        with self.assertRaises(Exception):
            _termine("passo sintetico", "filettatura")


class SeedTests(TestCase):
    def test_seed_caricato_in_bozza(self):
        self.assertGreaterEqual(Termine.objects.filter(fonte="seed").count(), 80)
        self.assertFalse(Termine.objects.filter(fonte="seed").exclude(stato="bozza").exists())
        lamatura = Termine.objects.get(termine="lamatura")
        chiavi = set(lamatura.varianti.values_list("chiave", flat=True))
        self.assertTrue({"spot face", "⌴"} <= chiavi)

    def test_seed_coerente(self):
        categorie = {c for c, _ in Termine.CATEGORIE}
        tipi = {t for t, _ in Variante.TIPI}
        chiavi = []
        for t in TERMINI:
            self.assertIn(t["categoria"], categorie, t["termine"])
            self.assertLessEqual(len(t["definizione"]), 600, t["termine"])
            for tipo, testo, _l in t["varianti"]:
                self.assertIn(tipo, tipi, testo)
                chiavi.append(normalizza_chiave(testo))
        self.assertEqual(len(chiavi), len(set(chiavi)), "varianti duplicate nel seed")
        gdt = [t for t in TERMINI if t["categoria"] == "gdt" and t["norma_rif"] == "ISO 1101" and t["simbolo"]]
        self.assertGreaterEqual(len(gdt), 14)  # le 14 caratteristiche (con la zona proiettata)


class ImportCsvTests(TestCase):
    INTESTAZIONE = "termine;termine_en;categoria;definizione;simbolo;norma_rif;varianti\n"

    def test_righe_valide_e_invalide(self):
        Variante.objects.create(termine=_termine("esistente"), testo="occupata", tipo="sinonimo")
        csv_txt = self.INTESTAZIONE + (
            "sfacciatura sintetica;facing;lavorazione;Definizione A;;;traduzione:facing|gergo:sfacciare\n"
            "riga senza categoria;;inesistente;Def;;;\n"
            "senza definizione;;lavorazione;;;;\n"
            "variante in conflitto;;lavorazione;Def;;;sinonimo:occupata\n"
            "variante malformata;;lavorazione;Def;;;senzatipo\n"
            "esistente;;lavorazione;Def;;;\n"
        )
        esito = services.importa_csv(csv_txt)
        self.assertEqual(esito.importati, 1)
        self.assertEqual(esito.saltati, 1)
        self.assertEqual(len(esito.errori), 4)
        nuovo = Termine.objects.get(termine="sfacciatura sintetica")
        self.assertEqual((nuovo.stato, nuovo.fonte), ("bozza", "import_csv"))
        self.assertEqual(set(nuovo.varianti.values_list("chiave", flat=True)), {"facing", "sfacciare"})
        self.assertFalse(Termine.objects.filter(termine="variante in conflitto").exists())

    def test_dry_run_e_comando(self):
        csv_txt = self.INTESTAZIONE + "zigrinatura sintetica;knurling;lavorazione;Def;;;traduzione:knurling\n"
        self.assertEqual(services.importa_csv(csv_txt, dry_run=True).importati, 1)
        self.assertFalse(Termine.objects.filter(termine="zigrinatura sintetica").exists())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.csv"
            path.write_text(csv_txt, encoding="utf-8")
            out = io.StringIO()
            call_command("glossario_import_csv", "--file", str(path), stdout=out)
        self.assertIn("importate=1", out.getvalue())
        self.assertTrue(Termine.objects.filter(termine="zigrinatura sintetica").exists())

    def test_intestazione_sbagliata(self):
        esito = services.importa_csv("a;b\n1;2\n")
        self.assertTrue(esito.errori and "colonne mancanti" in esito.errori[0])


class CandidatiTests(TestCase):
    TESTI = [
        "Controllo con rugosimetro portatile.\nLa sabbiatura fine precede la verniciatura.",
        "Il rugosimetro portatile va tarato.\nVerifica del rugosimetro portatile.",
        "Rugosimetro portatile in reparto. Firmato Zebedeo.",
        "Zebedeo controlla. Lamatura eseguita.",
        "Zebedeo verifica. Lamatura conforme.",
    ]

    def test_deterministico_senza_noti_e_persone(self):
        User.objects.create_user(username="z1", password="x", first_name="Zebedeo", last_name="Sintetico")
        _termine("rugosimetro portatile", "controllo_qualita")
        elenco = services.candidati(self.TESTI, min_documenti=3)
        testi = [c["testo"] for c in elenco]
        self.assertIn("rugosimetro", testi)
        self.assertNotIn("rugosimetro portatile", testi)  # già nel glossario
        self.assertNotIn("lamatura", testi)  # già nel seed
        self.assertNotIn("zebedeo", testi)   # nome di un utente: mai proposto
        self.assertNotIn("sabbiatura fine", testi)  # sotto la soglia documenti
        self.assertEqual(elenco, services.candidati(self.TESTI, min_documenti=3))

    def test_comando_senza_corpus(self):
        out = io.StringIO()
        call_command("glossario_candidati", stdout=out)
        self.assertIn("sgi_estrai_testi", out.getvalue())


class _FintaRisposta:
    def __init__(self, content):
        self.content = content


class ProposteAiTests(TestCase):
    def _risposta(self, voci):
        return _FintaRisposta("Ecco:\n" + json.dumps(voci, ensure_ascii=False))

    def test_proposte_valide_registrate_e_invalide_scartate(self):
        from ai_assistant.models import AiProposta

        voci = [
            {"candidato": "rugosimetro portatile", "termine": "rugosimetro", "categoria": "controllo_qualita",
             "definizione": "Strumento che misura la rugosità.", "varianti": [{"tipo": "traduzione", "testo": "roughness tester"},
                                                                             {"tipo": "inventato", "testo": "x"}]},
            {"candidato": "fuori elenco", "termine": "x", "categoria": "lavorazione", "definizione": "y"},
            {"candidato": "verniciatura", "termine": "verniciatura", "categoria": "scarta", "definizione": "y"},
        ]
        with patch("ai_assistant.services.chat_with_ollama", return_value=self._risposta(voci)):
            n = services.proponi_con_ai(["rugosimetro portatile", "verniciatura"])
        self.assertEqual(n, 1)
        p = AiProposta.objects.get(modulo="glossario")
        self.assertEqual(p.proposta["varianti"], ["traduzione:roughness tester"])
        self.assertEqual(p.oggetto_ref, "cand:rugosimetro portatile")

    def test_json_malformato_e_ai_spenta(self):
        from ai_assistant.models import AiProposta
        from ai_assistant.services import OllamaChatError

        with patch("ai_assistant.services.chat_with_ollama", return_value=_FintaRisposta("non è json [")):
            self.assertEqual(services.proponi_con_ai(["rugosimetro"]), 0)
        with patch("ai_assistant.services.chat_with_ollama", side_effect=OllamaChatError("giù")):
            self.assertEqual(services.proponi_con_ai(["rugosimetro"]), 0)
        self.assertFalse(AiProposta.objects.exists())


class ViewsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="gl_admin", password="x", is_superuser=True, is_staff=True)
        self.client.force_login(self.admin)
        self.t = _termine("lamatura sintetica")

    def _proposta(self):
        from ai_assistant.apprendimento import registra_proposta

        return registra_proposta(modulo="glossario", azione="nuovo_termine", oggetto_ref="cand:rugosimetro",
                                 proposta={"candidato": "rugosimetro", "termine": "rugosimetro",
                                           "categoria": "controllo_qualita", "definizione": "Strumento sintetico.",
                                           "varianti": ["traduzione:roughness tester"]})

    def test_pagine_gestore(self):
        for url in (reverse("glossario_tecnico:index"), reverse("glossario_tecnico:termine", args=[self.t.pk]),
                    reverse("glossario_tecnico:revisione"), reverse("glossario_tecnico:termine_nuovo"),
                    reverse("glossario_tecnico:index") + "?q=⌴"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, url)
            self.assertNotContains(resp, "{#")
        resp = self.client.get(reverse("glossario_tecnico:index") + "?q=spot face")
        self.assertContains(resp, "lamatura")  # trovata via variante del seed

    def test_variante_htmx_e_conflitto(self):
        url = reverse("glossario_tecnico:variante_aggiungi", args=[self.t.pk])
        resp = self.client.post(url, {"testo": "lamatura sintetica en", "tipo": "traduzione", "lingua": "en"})
        self.assertContains(resp, "lamatura sintetica en")
        resp = self.client.post(url, {"testo": "spot face", "tipo": "traduzione", "lingua": "en"})
        self.assertContains(resp, "già una variante")
        v = self.t.varianti.get()
        resp = self.client.post(reverse("glossario_tecnico:variante_elimina", args=[v.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(self.t.varianti.exists())

    def test_api_stato_valida(self):
        resp = self.client.post(reverse("glossario_tecnico:api_stato", args=[self.t.pk]), {"stato": "validato"})
        self.assertEqual(resp.json(), {"ok": True, "id": self.t.pk, "stato": "validato"})
        self.t.refresh_from_db()
        self.assertEqual(self.t.validato_da, self.admin)
        resp = self.client.post(reverse("glossario_tecnico:api_stato", args=[self.t.pk]), {"stato": "boh"})
        self.assertEqual(resp.status_code, 400)

    def test_api_cerca(self):
        resp = self.client.get(reverse("glossario_tecnico:api_cerca"), {"q": "FAI"})
        termini = [r["termine"] for r in resp.json()["risultati"]]
        self.assertIn("ispezione del primo articolo", termini)

    def test_proposta_accettata_registra_decisione(self):
        from ai_assistant.models import AiProposta

        p = self._proposta()
        resp = self.client.post(reverse("glossario_tecnico:proposta_decidi", args=[p.pk]), {"azione": "accetta"})
        self.assertEqual(resp.status_code, 302)
        nuovo = Termine.objects.get(termine="rugosimetro")
        self.assertEqual((nuovo.stato, nuovo.fonte), ("validato", "ai_proposta"))
        self.assertTrue(nuovo.varianti.filter(chiave="roughness tester").exists())
        self.assertEqual(AiProposta.objects.get(pk=p.pk).esito, AiProposta.ACCETTATA)

    def test_proposta_corretta_e_scartata(self):
        from ai_assistant.models import AiProposta

        p = self._proposta()
        self.assertEqual(self.client.get(reverse("glossario_tecnico:proposta_decidi", args=[p.pk])).status_code, 200)
        self.client.post(reverse("glossario_tecnico:proposta_decidi", args=[p.pk]), {
            "azione": "correggi", "termine": "rugosimetro", "categoria": "controllo_qualita",
            "definizione": "Definizione riscritta dalla qualità, completamente diversa.", "varianti": "",
        })
        self.assertEqual(AiProposta.objects.get(pk=p.pk).esito, AiProposta.MODIFICATA)
        p2 = self._proposta()
        p2.oggetto_ref = "cand:altro"
        p2.save()
        self.client.post(reverse("glossario_tecnico:proposta_decidi", args=[p2.pk]), {"azione": "scarta"})
        self.assertEqual(AiProposta.objects.get(pk=p2.pk).esito, AiProposta.SCARTATA)


class AclTests(TestCase):
    def setUp(self):
        self.t = _termine("lamatura sintetica")

    def test_api_anonimo_401_json(self):
        resp = self.client.get(reverse("glossario_tecnico:api_cerca"), {"q": "x"})
        self.assertIn(resp.status_code, (401, 403))
        self.assertEqual(resp["Content-Type"].split(";")[0], "application/json")

    def test_api_stato_senza_gestione_403_json(self):
        utente = User.objects.create_user(username="gl_lettore", password="x")
        self.client.force_login(utente)
        with patch("glossario_tecnico.views._has_perm", side_effect=lambda req, code: code == PERM_VIEW), \
                patch("core.middleware.ACLMiddleware.__call__", autospec=True,
                      side_effect=lambda self, request: self.get_response(request)):
            resp = self.client.post(reverse("glossario_tecnico:api_stato", args=[self.t.pk]), {"stato": "validato"})
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(resp.json()["ok"], False)
            # la consultazione resta permessa
            self.assertEqual(self.client.get(reverse("glossario_tecnico:index")).status_code, 200)
            self.assertNotEqual(self.client.get(reverse("glossario_tecnico:revisione")).status_code, 200)
        self.t.refresh_from_db()
        self.assertEqual(self.t.stato, "bozza")

    def test_utente_senza_permessi_non_vede(self):
        utente = User.objects.create_user(username="gl_nessuno", password="x")
        self.client.force_login(utente)
        with patch("glossario_tecnico.views._has_perm", return_value=False):
            self.assertNotEqual(self.client.get(reverse("glossario_tecnico:index")).status_code, 200)
            resp = self.client.get(reverse("glossario_tecnico:api_cerca"), {"q": "x"})
            self.assertEqual(resp.status_code, 403)

    def test_bootstrap_crea_permessi_e_binding(self):
        from core.models import PermissionDefinition, RoutePermissionBinding

        from .acl_bootstrap import PERM_GESTIONE, _bootstrap_canonical

        _bootstrap_canonical()
        self.assertTrue(PermissionDefinition.objects.filter(code=PERM_GESTIONE).exists())
        self.assertEqual(
            RoutePermissionBinding.objects.get(route_name="glossario_tecnico:api_stato").permission_id, PERM_GESTIONE,
        )
