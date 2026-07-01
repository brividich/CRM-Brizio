"""Test del Copilota AI incidenti/RCA (Fase 2 - A2): analisi proposta validata,
fail-safe e gate ACL dell'endpoint. L'AI e' sempre mockata (nessuna rete)."""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from rilevazione_incidenti import ai_copilota
from rilevazione_incidenti.models import SicurezzaImpostazioni, TipoEventoSicurezza

User = get_user_model()


def _set_acl(*, preposti=None, rspp=None):
    cfg, _ = SicurezzaImpostazioni.objects.get_or_create(pk=1)
    cfg.acl_preposti = list(preposti or [])
    cfg.acl_rspp = list(rspp or [])
    cfg.save()
    return cfg


class IncidentiCopilotaUnitTests(TestCase):
    def test_proposta_valida_e_liste(self):
        fake = json.dumps({
            "tipo_evento": "NEAR_MISS",  # case diverso -> normalizzato
            "causa_evento": "Mancata segregazione dell'area di manovra.",
            "cinque_perche": ["perche' 1", "perche' 2", "perche' 3"],
            "azioni_correttive": ["Installare barriera", "Formazione operatori"],
            "motivazione": "Nessun ferito ma potenziale alto.",
        })
        with patch.object(ai_copilota, "_chiama_ai", return_value=fake):
            out = ai_copilota.proponi_analisi_incidente(
                descrizione_attivita="movimentazione carrello",
                descrizione_avvenimento="operatore quasi investito",
            )
        self.assertTrue(out["proposto"])
        self.assertTrue(out["ai_disponibile"])
        self.assertEqual(out["tipo_evento"], TipoEventoSicurezza.NEAR_MISS)
        self.assertEqual(len(out["cinque_perche"]), 3)
        self.assertEqual(len(out["azioni_correttive"]), 2)

    def test_tipo_evento_fuori_catalogo_scartato(self):
        fake = json.dumps({"tipo_evento": "catastrofe", "cinque_perche": "non una lista"})
        with patch.object(ai_copilota, "_chiama_ai", return_value=fake):
            out = ai_copilota.proponi_analisi_incidente(
                descrizione_attivita="x", descrizione_avvenimento="y"
            )
        self.assertEqual(out["tipo_evento"], "")
        self.assertEqual(out["cinque_perche"], [])

    def test_failsafe_ai_offline(self):
        with patch.object(ai_copilota, "_chiama_ai", return_value=""):
            out = ai_copilota.proponi_analisi_incidente(
                descrizione_attivita="x", descrizione_avvenimento="y"
            )
        self.assertTrue(out["proposto"])
        self.assertFalse(out["ai_disponibile"])
        self.assertEqual(out["tipo_evento"], "")


class IncidentiCopilotaEndpointTests(TestCase):
    def setUp(self):
        self.url = reverse("rilevazione_incidenti:api_copilota_incidente")

    def test_forbidden_for_non_preposto(self):
        # Superuser per bypassare la middleware ACL di route e testare il gate INTERNO:
        # con una whitelist preposti che non lo include (e non e' legacy_admin) -> 403.
        _set_acl(preposti=["altro@x.it"], rspp=[])
        user = User.objects.create_superuser(username="incid-nobody", password="pass12345", email="n@x.it")
        self.client.force_login(user)
        resp = self.client.post(
            self.url,
            data=json.dumps({"descrizione_avvenimento": "x"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_returns_proposal_for_preposto(self):
        # acl_preposti vuota = accesso aperto (semantica del modulo). Superuser -> bypassa
        # la middleware ACL di route; il gate interno consente -> 200.
        _set_acl(preposti=[], rspp=[])
        user = User.objects.create_superuser(username="incid-op", password="pass12345", email="o@x.it")
        self.client.force_login(user)
        fake = json.dumps({"tipo_evento": "incidente", "causa_evento": "caduta dall'alto"})
        with patch.object(ai_copilota, "_chiama_ai", return_value=fake):
            resp = self.client.post(
                self.url,
                data=json.dumps({"descrizione_avvenimento": "caduta da scala"}),
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["proposta"]["tipo_evento"], "incidente")

    def test_requires_descrizione(self):
        _set_acl(preposti=[], rspp=[])
        user = User.objects.create_superuser(username="incid-op2", password="pass12345", email="o2@x.it")
        self.client.force_login(user)
        resp = self.client.post(self.url, data=json.dumps({}), content_type="application/json")
        self.assertEqual(resp.status_code, 400)
