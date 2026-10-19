"""Viste bi_* e API dati /api/v1/ (dati sintetici)."""
from __future__ import annotations

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

from dati_bi import viste
from dati_bi.models import ApiClient

# Colonne che non devono mai uscire dalle viste: persone, contatti, testi liberi.
COLONNE_VIETATE = {
    "assignment_to", "assigned_to_id", "executed_by_id", "assigned_legacy_user_id", "richiedente_nome",
    "richiedente_email", "richiedente_legacy_id", "richiedente_legacy_user_id", "assegnato_a", "assegnato_email",
    "responsabile_id", "descrizione", "description", "notes", "note", "firma_immagine", "account_email",
    "assigned_to_display", "email",
}


def _oggi():
    return timezone.localdate()


class _Dati(TestCase):
    @classmethod
    def setUpTestData(cls):
        from assets.models import (
            Asset, AssetAdministrativeDeadline, PeriodicCheckSystem, PeriodicCheckType, WorkOrder,
        )
        from dpi.models import CategoriaDPI, ConsegnaDPI, RichiestaDPI, StatoRichiesta

        cls.asset = Asset.objects.create(
            asset_tag="BI-001", name="Tornio sintetico", reparto="OFFICINA", assignment_to="Persona Da Non Esporre",
        )
        AssetAdministrativeDeadline.objects.create(
            asset=cls.asset, title="Revisione sintetica", due_date=_oggi() + timedelta(days=10), is_active=True,
        )
        system = PeriodicCheckSystem.objects.create(name="Antincendio sintetico")
        PeriodicCheckType.objects.create(system=system, name="Estintori", next_due_date=_oggi() - timedelta(days=2))
        WorkOrder.objects.create(asset=cls.asset, title="Sostituzione cinghia", description="Testo libero riservato")
        cat = CategoriaDPI.objects.create(nome="Guanti sintetici")
        r = RichiestaDPI.objects.create(
            categoria=cat, richiedente_nome="Mario Sintetico", richiedente_reparto="OFFICINA",
            stato=StatoRichiesta.CONSEGNATA,
        )
        ConsegnaDPI.objects.create(richiesta=r, data_consegna=_oggi(), data_scadenza_stimata=_oggi() + timedelta(days=5))


class VisteTests(_Dati):
    def _righe(self, nome):
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT * FROM {nome}")
            colonne = [c[0] for c in cursor.description]
            return colonne, cursor.fetchall()

    def test_tutte_le_viste_esistono_e_si_leggono(self):
        for nome in viste.VISTE:
            with self.subTest(vista=nome):
                colonne, _ = self._righe(nome)
                self.assertTrue(colonne)

    def test_nessuna_colonna_personale_o_testo_libero(self):
        for nome in viste.VISTE:
            with self.subTest(vista=nome):
                colonne, _ = self._righe(nome)
                self.assertFalse(COLONNE_VIETATE & {c.lower() for c in colonne}, colonne)

    def test_scadenze_asset_unisce_le_fonti(self):
        colonne, righe = self._righe("bi_scadenze_asset")
        fonti = {r[colonne.index("fonte")] for r in righe}
        self.assertEqual(fonti, {"amministrativa", "verifica_impianto"})

    def test_dpi_e_odl_senza_nominativi(self):
        colonne, righe = self._righe("bi_dpi_consegne")
        self.assertNotIn("Mario Sintetico", str(righe))
        self.assertEqual(righe[0][colonne.index("in_essere")], 1)
        _, righe = self._righe("bi_ordini_lavoro")
        self.assertNotIn("Testo libero riservato", str(righe))
        _, righe = self._righe("bi_asset")
        self.assertNotIn("Persona Da Non Esporre", str(righe))

    def test_sql_server_create_or_alter_e_grant(self):
        stmts = viste.statements_crea("microsoft")
        self.assertEqual(len(stmts), len(viste.VISTE))
        self.assertTrue(all(s.startswith("CREATE OR ALTER VIEW bi_") for s in stmts))
        self.assertIn("GRANT SELECT ON bi_asset TO [NOVICROM\\powerbi_reader]", viste.statements_grant("NOVICROM\\powerbi_reader"))
        with self.assertRaises(ValueError):
            viste.statements_grant("x]; DROP TABLE assets_asset; --")

    def test_comando_bi_viste(self):
        out = StringIO()
        call_command("bi_viste", "--applica", stdout=out)
        self.assertIn("bi_scadenze_asset: 2 righe", out.getvalue())
        out = StringIO()
        call_command("bi_viste", "--grant", "powerbi_reader", stdout=out)
        self.assertIn("GRANT SELECT ON bi_capa TO [powerbi_reader];", out.getvalue())


@override_settings(DATI_API_ALLOWED_IPS=["127.0.0.1"])
class ApiTests(_Dati):
    def setUp(self):
        self.token = ApiClient.nuovo_token()
        self.client_app = ApiClient(nome="Power BI sintetico", ambiti=["asset", "manutenzione", "scadenze"])
        self.client_app.imposta_token(self.token)
        self.client_app.save()

    def _get(self, path, token=None, **extra):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {token if token is not None else self.token}"}
        headers.update(extra)
        return self.client.get(path, **headers)

    def test_senza_token_401_json(self):
        resp = self.client.get("/api/v1/stato/")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp["Content-Type"], "application/json; charset=utf-8")
        self.assertEqual(self._get("/api/v1/stato/", token="sbagliato").status_code, 401)

    def test_token_disattivato_401(self):
        self.client_app.attivo = False
        self.client_app.save()
        self.assertEqual(self._get("/api/v1/stato/").status_code, 401)

    @override_settings(DATI_API_ALLOWED_IPS=["10.99.0.0/16"])
    def test_rete_non_ammessa_403(self):
        self.assertEqual(self._get("/api/v1/stato/").status_code, 403)

    def test_stato_e_ultimo_accesso(self):
        data = self._get("/api/v1/stato/").json()
        self.assertEqual(data["applicazione"], "Power BI sintetico")
        self.client_app.refresh_from_db()
        self.assertIsNotNone(self.client_app.ultimo_accesso)
        self.assertFalse(ApiClient.objects.filter(token_hash=self.token).exists())  # mai in chiaro

    def test_ambito_mancante_403(self):
        self.client_app.ambiti = ["asset"]
        self.client_app.save()
        self.assertEqual(self._get("/api/v1/ordini-lavoro/").status_code, 403)

    def test_asset_paginati_senza_assegnatario(self):
        resp = self._get("/api/v1/asset/?limit=1")
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["items"][0]["asset_tag"], "BI-001")
        self.assertNotIn("Persona Da Non Esporre", resp.content.decode())

    def test_limite_massimo_pagina(self):
        resp = self._get("/api/v1/asset/?limit=100000")
        self.assertEqual(resp.status_code, 200)

    def test_ordini_lavoro_senza_testi_liberi(self):
        resp = self._get("/api/v1/ordini-lavoro/")
        self.assertEqual(resp.status_code, 200, resp.content)
        item = resp.json()["items"][0]
        self.assertEqual(item["titolo"], "Sostituzione cinghia")
        self.assertEqual(item["asset_tag"], "BI-001")
        self.assertNotIn("Testo libero riservato", resp.content.decode())

    def test_scadenze_senza_nominativi_e_senza_personale(self):
        resp = self._get("/api/v1/scadenze/?limit=500")
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.content.decode()
        self.assertNotIn("Mario Sintetico", body)
        fonti = {i["fonte"] for i in resp.json()["items"]}
        self.assertNotIn("hr", fonti)
        self.assertTrue({"asset", "impianti", "dpi"} <= fonti, fonti)
        dpi = next(i for i in resp.json()["items"] if i["fonte"] == "dpi")
        self.assertEqual(dpi["soggetto"], "")
        scaduta = next(i for i in resp.json()["items"] if i["titolo"] == "Estintori")
        self.assertEqual(scaduta["stato"], "scaduta")

    def test_scadenze_fonte_non_valida_400(self):
        self.assertEqual(self._get("/api/v1/scadenze/?fonte=hr").status_code, 400)

    def _voce_hr(self):
        return [{
            "kind": "visita", "kind_label": "Visita medica", "legacy_id": 1, "cognome": "ROSSI", "nome": "ANNA",
            "reparto": "OFFICINA", "tipo_nome": "Visita periodica", "data_scadenza": _oggi() - timedelta(days=1),
            "giorni": -1, "scaduta": True,
        }]

    def test_riepilogo_personale_solo_con_ambito_e_solo_conteggi(self):
        with patch("anagrafica.views._build_scadenzario_voci", return_value=self._voce_hr()):
            senza = self._get("/api/v1/scadenze/riepilogo/").json()
            self.assertFalse([r for r in senza if r["fonte"] == "hr"])
            self.client_app.ambiti = ["scadenze", "personale_aggregato"]
            self.client_app.save()
            resp = self._get("/api/v1/scadenze/riepilogo/")
        con = resp.json()
        hr = [r for r in con if r["fonte"] == "hr"]
        self.assertEqual(hr, [{"fonte": "hr", "tipo": "visita", "tipo_etichetta": "Visita medica",
                               "reparto": "OFFICINA", "stato": "scaduta", "quante": 1}])
        self.assertNotIn("ROSSI", resp.content.decode())

    def test_provider_reali_con_identita_di_servizio_non_falliscono(self):
        # collect_all ingoia gli errori dei provider: qui si controlla che con
        # l'identità di servizio nessuna sorgente salti in silenzio.
        from dati_bi.api import _voci

        with self.assertNoLogs("dashboard.scadenze_providers", level="ERROR"):
            voci = _voci({"hr", "asset", "impianti", "dpi", "rentri", "capa"})
        self.assertTrue({"asset", "impianti", "dpi"} <= {v.source for v in voci})

    def test_openapi_solo_amministratori(self):
        self.assertNotEqual(self.client.get("/api/v1/openapi.json").status_code, 200)
        staff = get_user_model().objects.create_user("bi-staff", password="pw", is_staff=True, is_superuser=True)
        self.client.force_login(staff)
        resp = self.client.get("/api/v1/openapi.json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("/api/v1/scadenze/", resp.content.decode())


class ComandoClientTests(TestCase):
    def test_crea_stampa_token_una_volta_e_salva_hash(self):
        out = StringIO()
        call_command("dati_api_client", "crea", "Power BI", "--ambito", "scadenze", stdout=out)
        token = [line for line in out.getvalue().splitlines() if line.startswith("pnh_")][0]
        client = ApiClient.objects.get(nome="Power BI")
        self.assertEqual(client.token_hash, ApiClient.hash_token(token))
        self.assertEqual(client.ambiti, ["scadenze"])

    def test_ambito_sconosciuto_e_duplicato(self):
        with self.assertRaises(CommandError):
            call_command("dati_api_client", "crea", "X", "--ambito", "tutto", stdout=StringIO())
        call_command("dati_api_client", "crea", "X", "--ambito", "asset", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("dati_api_client", "crea", "X", "--ambito", "asset", stdout=StringIO())

    def test_disattiva_e_rigenera(self):
        call_command("dati_api_client", "crea", "X", "--ambito", "asset", stdout=StringIO())
        vecchio = ApiClient.objects.get(nome="X").token_hash
        call_command("dati_api_client", "rigenera", "X", stdout=StringIO())
        call_command("dati_api_client", "disattiva", "X", stdout=StringIO())
        client = ApiClient.objects.get(nome="X")
        self.assertNotEqual(client.token_hash, vecchio)
        self.assertFalse(client.attivo)
