"""Test degli export tabellari dell'area «Qualifiche / MPQ / Skill matrix».

Un test per key registrata: la spec esiste nel registry e `build_export_response`
produce sia lo .xlsx sia il .pdf con le righe attese. Dati esclusivamente sintetici.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.exports import EXPORT_SPECS, build_export_response
from anagrafica.models import DipendenteQualifica, QualificaSessione, TipoQualifica
from anagrafica.models_mpq import ClienteQualificante
from core.models import AuditLog

# Riuso dell'helper che crea la tabella legacy `anagrafica_dipendenti` nel DB di test.
from anagrafica.tests import _ensure_anagrafica_table

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class QualificheExportTests(TestCase):
    """Le 5 liste dell'area, con dati sintetici (nessun dato reale)."""

    def setUp(self):
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            for alias, nome, cognome, reparto in [
                ("t.uno", "Tizio", "Uno", "REPARTO A"),
                ("c.due", "Caio", "Due", "REPARTO B"),
            ]:
                cursor.execute(
                    "INSERT INTO anagrafica_dipendenti "
                    "(aliasusername, nome, cognome, reparto, attivo) VALUES (%s,%s,%s,%s,%s)",
                    [alias, nome, cognome, reparto, 1],
                )
            cursor.execute("SELECT id, aliasusername FROM anagrafica_dipendenti")
            ids = {row[1]: int(row[0]) for row in cursor.fetchall()}
        self.lid_uno = ids["t.uno"]
        self.lid_due = ids["c.due"]

        self.admin = User.objects.create_superuser("admin_exp_qual", "a@example.invalid", "x")
        self.client.force_login(self.admin)

        oggi = timezone.localdate()

        self.tipo_sic = TipoQualifica.objects.create(
            nome="Addetto antincendio (test)",
            categoria=TipoQualifica.CAT_SICUREZZA,
            durata_mesi=60,
        )
        self.tipo_prof = TipoQualifica.objects.create(
            nome="Patentino carrellista (test)",
            categoria=TipoQualifica.CAT_PROFESSIONALE,
            durata_mesi=0,
        )

        # Uno: qualifica sicurezza SCADUTA · Due: qualifica professionale VALIDA
        DipendenteQualifica.objects.create(
            legacy_anagrafica_id=self.lid_uno,
            tipo=self.tipo_sic,
            data_conseguimento=oggi - timedelta(days=800),
            data_scadenza=oggi - timedelta(days=10),
            ente="Ente Sintetico",
        )
        DipendenteQualifica.objects.create(
            legacy_anagrafica_id=self.lid_due,
            tipo=self.tipo_prof,
            data_conseguimento=oggi - timedelta(days=100),
            data_scadenza=oggi + timedelta(days=400),
        )

        QualificaSessione.objects.create(
            tipo=self.tipo_sic,
            data_conseguimento=oggi - timedelta(days=30),
            data_scadenza=oggi + timedelta(days=1000),
            ente="Ente Sintetico",
        )
        QualificaSessione.objects.create(
            tipo=self.tipo_prof,
            data_conseguimento=oggi - timedelta(days=60),
            ente="Altro Ente",
        )

        cert = ClienteQualificante.objects.create(
            nome="Organismo Sintetico",
            tipo=ClienteQualificante.TIPO_ORGANISMO_CERTIFICAZIONE,
        )
        ClienteQualificante.objects.create(
            nome="Cliente Sintetico",
            tipo=ClienteQualificante.TIPO_CLIENTE,
            codice="CS-001",
            certificatore=cert,
        )

    # -- helper ---------------------------------------------------------------
    def _url(self, key, **params):
        url = reverse("anagrafica:export", args=[key])
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        return url

    def _assert_both_formats(self, key, expected_rows, **params):
        """La spec è registrata e produce xlsx + pdf con `expected_rows` righe."""
        self.assertIn(key, EXPORT_SPECS)

        resp = self.client.get(self._url(key, format="xlsx", **params))
        self.assertEqual(resp.status_code, 200, key)
        self.assertEqual(resp["Content-Type"], XLSX_CT)
        self.assertIn(key, resp["Content-Disposition"])
        log = AuditLog.objects.filter(azione="export").latest("id")
        self.assertEqual(log.dettaglio.get("lista"), key)
        self.assertEqual(log.dettaglio.get("n_righe"), expected_rows, f"{key} (xlsx)")

        resp = self.client.get(self._url(key, format="pdf", **params))
        self.assertEqual(resp.status_code, 200, key)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))
        log = AuditLog.objects.filter(azione="export").latest("id")
        self.assertEqual(log.dettaglio.get("n_righe"), expected_rows, f"{key} (pdf)")

    def _rows(self, key, scope="filtered", **params):
        from django.test import RequestFactory

        request = RequestFactory().get("/anagrafica/esporta/%s/" % key, params)
        request.user = self.admin
        return EXPORT_SPECS[key].dataset(request, scope)

    # -- 1. catalogo qualifiche ----------------------------------------------
    def test_export_qualifiche(self):
        self._assert_both_formats("qualifiche", 2)
        # Filtro `categoria` = tab della pagina.
        self._assert_both_formats("qualifiche", 1, categoria="SICUREZZA")
        rows = self._rows("qualifiche", categoria="SICUREZZA")
        self.assertEqual(rows[0]["nome"], self.tipo_sic.nome)
        self.assertEqual(rows[0]["durata"], "60 mesi")
        self.assertEqual(rows[0]["n_assegnazioni"], 1)
        self.assertEqual(rows[0]["stato"], "Attiva")
        # scope=full ignora la querystring.
        self.assertEqual(len(self._rows("qualifiche", scope="full", categoria="SICUREZZA")), 2)

    # -- 2. scadenzario -------------------------------------------------------
    def test_export_qualifiche_scadenzario(self):
        # Default della pagina: «da gestire» = scadute + ≤60gg → solo la scaduta.
        self._assert_both_formats("qualifiche_scadenzario", 1)
        rows = self._rows("qualifiche_scadenzario")
        self.assertEqual(rows[0]["dipendente"], "Uno Tizio")
        self.assertEqual(rows[0]["reparto"], "REPARTO A")
        self.assertEqual(rows[0]["qualifica"], self.tipo_sic.nome)
        self.assertEqual(rows[0]["stato"], "Scaduta")
        self.assertEqual(rows[0]["ente"], "Ente Sintetico")
        self.assertEqual(rows[0]["evidenza"], "No")
        # stato=tutte → entrambe; stato=valide → solo quella valida.
        self._assert_both_formats("qualifiche_scadenzario", 2, stato="tutte")
        self._assert_both_formats("qualifiche_scadenzario", 1, stato="valide")
        # Filtro reparto e categoria.
        self.assertEqual(len(self._rows("qualifiche_scadenzario", stato="tutte", reparto="REPARTO B")), 1)
        self.assertEqual(
            len(self._rows("qualifiche_scadenzario", stato="tutte", categoria="PROFESSIONALE")), 1
        )
        # scope=full = tutte le assegnazioni, filtri ignorati.
        self.assertEqual(len(self._rows("qualifiche_scadenzario", scope="full")), 2)

    # -- 3. sessioni di rinnovo ----------------------------------------------
    def test_export_qualifica_sessioni(self):
        self._assert_both_formats("qualifica_sessioni", 2)
        rows = self._rows("qualifica_sessioni", q="Altro")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["qualifica"], self.tipo_prof.nome)
        self.assertEqual(rows[0]["ente"], "Altro Ente")
        self.assertEqual(rows[0]["partecipanti"], 0)
        # Filtro per tipo.
        self._assert_both_formats("qualifica_sessioni", 1, tipo=self.tipo_sic.id)
        # scope=full ignora la ricerca.
        self.assertEqual(len(self._rows("qualifica_sessioni", scope="full", q="Altro")), 2)

    # -- 4. matrice competenze -----------------------------------------------
    def test_export_matrice_competenze(self):
        # Una riga per dipendente attivo (tabella piatta: colonne = conteggi+elenchi).
        self._assert_both_formats("matrice_competenze", 2)
        rows = {r["dipendente"]: r for r in self._rows("matrice_competenze")}
        uno = rows["Uno Tizio"]
        self.assertEqual(uno["n_scadute"], 1)
        self.assertEqual(uno["n_valide"], 0)
        self.assertEqual(uno["n_mancanti"], 1)  # non possiede la professionale
        self.assertIn(self.tipo_sic.nome, uno["scadute"])
        due = rows["Due Caio"]
        self.assertEqual(due["n_valide"], 1)
        self.assertIn(self.tipo_prof.nome, due["valide"])
        # Filtro reparto.
        self._assert_both_formats("matrice_competenze", 1, reparto="REPARTO+A")
        # Filtro categoria: solo la competenza di sicurezza resta a colonna.
        cat_rows = {r["dipendente"]: r for r in self._rows("matrice_competenze", categoria="SICUREZZA")}
        self.assertEqual(cat_rows["Due Caio"]["n_mancanti"], 1)
        self.assertEqual(cat_rows["Due Caio"]["n_valide"], 0)

    # -- 5. clienti/enti MOD.128 ---------------------------------------------
    def test_export_mpq_clienti(self):
        self._assert_both_formats("mpq_clienti", 2)
        rows = {r["nome"]: r for r in self._rows("mpq_clienti")}
        cliente = rows["Cliente Sintetico"]
        self.assertEqual(cliente["tipo"], "Cliente")
        self.assertEqual(cliente["codice"], "CS-001")
        self.assertEqual(cliente["certificatore"], "Organismo Sintetico")
        self.assertEqual(cliente["attivo"], "Sì")

    # -- invarianti trasversali ----------------------------------------------
    def test_ogni_spec_riempie_tutte_le_colonne_dichiarate(self):
        for key in (
            "qualifiche",
            "qualifiche_scadenzario",
            "qualifica_sessioni",
            "matrice_competenze",
            "mpq_clienti",
        ):
            spec = EXPORT_SPECS[key]
            accessors = {accessor for _label, accessor in spec.columns}
            rows = self._rows(key, scope="full")
            self.assertTrue(rows, f"dataset '{key}' vuoto")
            for row in rows:
                self.assertEqual(accessors - set(row), set(), f"colonne mancanti in '{key}'")

    def test_build_export_response_diretto(self):
        """`build_export_response` è usabile anche fuori dalla view (contratto)."""
        from django.test import RequestFactory

        request = RequestFactory().get("/anagrafica/esporta/mpq_clienti/")
        request.user = self.admin
        resp = build_export_response(request, "mpq_clienti", "xlsx", "full")
        self.assertEqual(resp["Content-Type"], XLSX_CT)
