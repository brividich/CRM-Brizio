"""Test del Copilota AI anomalie (Fase 2 - A3): proposta di triage validata,
fail-safe e gate ACL dell'endpoint. L'AI e' sempre mockata (nessuna rete)."""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from anomalie import ai_copilota

User = get_user_model()

STATI = ["Finito macchinato", "Con sovrametallo", "Finito trattato"]
AVANZ = ["Accetto lo stato", "In attesa", "Finito trattato"]


class AnomalieCopilotaUnitTests(TestCase):
    def test_proposta_normalizza_su_liste_reali(self):
        fake = json.dumps({
            "stato_superficie": "con sovrametallo",  # case diverso -> normalizzato
            "avanzamento": "In attesa",
            "serve_rdc": True,
            "bozza_descrizione": "Eccesso di materiale sulla superficie.",
            "motivazione": "Sovrametallo evidente.",
        })
        with patch.object(ai_copilota, "_chiama_ai", return_value=fake):
            out = ai_copilota.proponi_triage_anomalia(
                descrizione="c'e' troppo materiale", stati_superficie=STATI, avanzamenti=AVANZ
            )
        self.assertTrue(out["proposto"])
        self.assertTrue(out["ai_disponibile"])
        self.assertEqual(out["stato_superficie"], "Con sovrametallo")
        self.assertEqual(out["avanzamento"], "In attesa")
        self.assertTrue(out["serve_rdc"])

    def test_valori_fuori_lista_scartati(self):
        fake = json.dumps({"stato_superficie": "Inventato", "avanzamento": "Boh", "serve_rdc": "no"})
        with patch.object(ai_copilota, "_chiama_ai", return_value=fake):
            out = ai_copilota.proponi_triage_anomalia(
                descrizione="...", stati_superficie=STATI, avanzamenti=AVANZ
            )
        self.assertEqual(out["stato_superficie"], "")
        self.assertEqual(out["avanzamento"], "")
        self.assertTrue(out["serve_rdc"])  # bool("no") e' True: serve_rdc e' booleanizzato, non validato su lista

    def test_failsafe_ai_offline(self):
        with patch.object(ai_copilota, "_chiama_ai", return_value=""):
            out = ai_copilota.proponi_triage_anomalia(
                descrizione="...", stati_superficie=STATI, avanzamenti=AVANZ
            )
        self.assertTrue(out["proposto"])
        self.assertFalse(out["ai_disponibile"])
        self.assertEqual(out["stato_superficie"], "")


class AnomalieCopilotaEndpointTests(TestCase):
    def setUp(self):
        self.url = reverse("api_anomalie_copilota")

    def test_endpoint_forbidden_for_plain_user(self):
        user = User.objects.create_user(username="anom-op", password="pass12345")
        self.client.force_login(user)
        resp = self.client.post(
            self.url, data=json.dumps({"descrizione": "x"}), content_type="application/json"
        )
        self.assertEqual(resp.status_code, 403)

    def test_endpoint_returns_proposal_for_superuser(self):
        admin = User.objects.create_superuser(
            username="anom-admin", password="pass12345", email="a@b.c"
        )
        self.client.force_login(admin)
        fake = json.dumps({"stato_superficie": "Finito trattato", "serve_rdc": False})
        with patch("anomalie.views._load_anomalie_lists", return_value={
            "stati_superficie": STATI, "avanzamenti": AVANZ,
        }), patch.object(ai_copilota, "_chiama_ai", return_value=fake):
            resp = self.client.post(
                self.url,
                data=json.dumps({"descrizione": "pezzo trattato ok"}),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["proposta"]["stato_superficie"], "Finito trattato")
        self.assertFalse(data["proposta"]["serve_rdc"])

    def test_endpoint_requires_descrizione(self):
        admin = User.objects.create_superuser(
            username="anom-admin2", password="pass12345", email="a2@b.c"
        )
        self.client.force_login(admin)
        resp = self.client.post(self.url, data=json.dumps({}), content_type="application/json")
        self.assertEqual(resp.status_code, 400)
