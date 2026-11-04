"""Configurazione → «Campi del blocco del controllore»: regole «Visibile se». Dati sintetici."""
from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from anomalie import views as av

User = get_user_model()


class RegoleTests(TestCase):
    def _per(self, regole, nomi=frozenset(), ruoli_nomi=()):
        r = RequestFactory().get("/")
        r.user = User(username="x")
        with patch.object(av, "_read_anomalie_config", return_value={"campi_controllo": regole}), \
                patch.object(av, "_request_name_norms", return_value=set(nomi)), \
                patch.object(av, "_current_user_identity", return_value={"email_norm": ""}), \
                patch.object(av, "_names_for_ruoli_operativi", return_value=list(ruoli_nomi)):
            return av.campi_controllo_per(r)

    def test_di_serie_tutto_visibile(self):
        out = self._per({})
        self.assertTrue(all(v["visibile"] and not v["fasi"] and not v["tipi"] for v in out.values()))

    def test_formato_vecchio_bool_e_mai(self):
        out = self._per({"simboli": False, "caso": {"modo": "mai"}})
        self.assertFalse(out["simboli"]["visibile"])
        self.assertFalse(out["caso"]["visibile"])

    def test_persone_e_ruoli(self):
        regole = {"report_zeiss": {"modo": "se", "persone": ["Paolo Rossi"]},
                  "caso_misura": {"modo": "se", "ruoli": [3]}}
        out = self._per(regole, nomi={"ROSSI PAOLO"}, ruoli_nomi=["Anna Verdi"])
        self.assertTrue(out["report_zeiss"]["visibile"])   # nome in qualunque ordine
        self.assertFalse(out["caso_misura"]["visibile"])   # non ha il ruolo
        out2 = self._per(regole, nomi={"ANNA VERDI"}, ruoli_nomi=["Anna Verdi"])
        self.assertFalse(out2["report_zeiss"]["visibile"])
        self.assertTrue(out2["caso_misura"]["visibile"])

    def test_fasi_e_tipi_passano_alla_pagina(self):
        out = self._per({"report_zeiss": {"modo": "se", "fasi": ["CMM"], "tipi": ["fuori-tolleranza"]},
                         "dove_pezzi": {"modo": "se", "tipi": ["bave-spigoli"]}})
        self.assertEqual(out["report_zeiss"], {"visibile": True, "fasi": ["CMM"], "tipi": ["fuori-tolleranza"]})
        self.assertEqual(out["dove_pezzi"]["tipi"], [])  # di blocco: il tipo dell'anomalia non si applica


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class EndpointTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username="cfg-cc", password="pass12345", email="c@example.local")
        self.client.force_login(self.user)
        self.salvato = {}

    def test_salva_regole_pulite(self):
        with patch.object(av, "_read_anomalie_config", side_effect=lambda: dict(self.salvato)), \
                patch.object(av, "_write_anomalie_config", side_effect=lambda p: self.salvato.update(p)):
            r = self.client.post(reverse("api_anomalie_config_campi_controllo"), data=json.dumps({"campi": {
                "simboli": {"modo": "mai"},
                "report_zeiss": {"modo": "se", "fasi": [" CMM "], "ruoli": ["3", "x"], "persone": ["", "Paolo Rossi"]},
                "inventato": {"modo": "mai"},
            }}), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        regole = self.salvato["campi_controllo"]
        self.assertNotIn("inventato", regole)
        self.assertEqual(regole["simboli"]["modo"], "mai")
        self.assertEqual(regole["report_zeiss"], {"modo": "se", "persone": ["Paolo Rossi"], "ruoli": [3],
                                                  "fasi": ["CMM"], "tipi": []})
        self.assertEqual(regole["caso"]["modo"], "sempre")

    def test_pagina_configurazione_mostra_il_riquadro(self):
        r = self.client.get(reverse("anomalie_configurazione_page") + "?tab=config")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Campi del blocco del controllore")
        self.assertContains(r, 'data-campo="report_zeiss"')
