"""Test degli export tabellari (PDF/Excel) dell'area «Formazione».

Dati sintetici: nessun dato reale (HR/GDPR).
"""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from anagrafica.exports import EXPORT_SPECS
from anagrafica.models import (
    CategoriaCorso,
    EsposizioneRischio,
    FattoreRischio,
    Mansione,
    TrainingCourse,
    TrainingDeadline,
    TrainingInstructor,
    TrainingPlan,
    TrainingSession,
)
from core.legacy_models import AnagraficaDipendente
from core.models import AuditLog

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

User = get_user_model()

FORMAZIONE_KEYS = [
    "formazione_corsi",
    "formazione_sessioni",
    "formazione_piani",
    "formazione_istruttori",
    "formazione_scadenzario",
    "fattori_rischio",
    "categorie_corso",
    "esposizioni_rischio",
]


class FormazioneExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("admin_exp_form", "admin@example.invalid", "x")

        # ── Piani + corsi ────────────────────────────────────────────────────
        cls.piano_sic = TrainingPlan.objects.create(
            codice="PSIC", nome="Piano Sicurezza",
            categoria="OBBLIGATORIA", stato="ATTIVO", provider_esterno=True,
        )
        cls.piano_it = TrainingPlan.objects.create(
            codice="PIT", nome="Piano Informatica",
            categoria="FACOLTATIVA", stato="BOZZA",
        )
        cls.corso_a = TrainingCourse.objects.create(
            piano=cls.piano_sic, codice="C-ANTINC", titolo="Antincendio base",
            durata_ore_teorica=8, validita_mesi=36, obbligatorio=True, stato="ATTIVO",
        )
        cls.corso_b = TrainingCourse.objects.create(
            piano=cls.piano_it, codice="C-EXCEL", titolo="Excel avanzato",
            durata_ore_teorica=4, validita_mesi=0, obbligatorio=False, stato="BOZZA",
        )

        # ── Docenti ──────────────────────────────────────────────────────────
        cls.docente = TrainingInstructor.objects.create(
            tipo="ESTERNO", nome="Mario Docente Test",
            ragione_sociale="Formazione Test Srl",
            email="docente@example.invalid", telefono="000-0000000",
        )
        TrainingInstructor.objects.create(tipo="INTERNO", nome="Anna Interna Test")

        # ── Sessioni ─────────────────────────────────────────────────────────
        cls.sessione = TrainingSession.objects.create(
            corso=cls.corso_a, codice_sessione="S-2026-001", stato="COMPLETATA",
            modalita="IN_SEDE", data_inizio=date(2026, 3, 2), data_fine=date(2026, 3, 2),
            sede="Aula test", docente=cls.docente,
        )
        TrainingSession.objects.create(
            corso=cls.corso_b, codice_sessione="S-2025-009", stato="PIANIFICATA",
            modalita="REMOTO", data_inizio=date(2025, 11, 5), data_fine=date(2025, 11, 5),
        )

        # ── Scadenzario (dipendenti sintetici) ───────────────────────────────
        cls.dip = AnagraficaDipendente.objects.create(
            nome="Luca", cognome="Rossi Test", aliasusername="lrossi.test",
        )
        cls.dip2 = AnagraficaDipendente.objects.create(
            nome="Sara", cognome="Bianchi Test", aliasusername="sbianchi.test",
        )
        TrainingDeadline.objects.create(
            corso=cls.corso_a, legacy_anagrafica_id=cls.dip.id,
            data_scadenza=date(2026, 1, 10), stato_scadenza="SCADUTO",
            giorni_alla_scadenza=-30, is_required=True,
        )
        TrainingDeadline.objects.create(
            corso=cls.corso_b, legacy_anagrafica_id=cls.dip2.id,
            data_scadenza=date(2027, 1, 10), stato_scadenza="VALIDO",
            giorni_alla_scadenza=200, is_required=False,
        )

        # ── Rischi ───────────────────────────────────────────────────────────
        cls.fattore = FattoreRischio.objects.create(
            codice="F-RUM", nome="Rumore", categoria=FattoreRischio.CAT_FISICO,
            periodicita_formazione_mesi=60, periodicita_sorveglianza_mesi=12,
            richiede_visita_medica=True, richiede_dpi=True,
        )
        FattoreRischio.objects.create(
            codice="F-CHI", nome="Agenti chimici", categoria=FattoreRischio.CAT_CHIMICO,
        )
        cls.categoria = CategoriaCorso.objects.create(codice="CAT-SIC", nome="Sicurezza")
        cls.categoria.fattori_rischio.add(cls.fattore)
        cls.mansione = Mansione.objects.create(nome="Operatore test")
        EsposizioneRischio.objects.create(fattore=cls.fattore, mansione=cls.mansione, note="Nota test")

    def setUp(self):
        self.client.force_login(self.admin)

    # -- helper ---------------------------------------------------------------
    def _url(self, key, **params):
        url = reverse("anagrafica:export", args=[key])
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        return url

    def _last_log(self):
        return AuditLog.objects.filter(azione="export").latest("id")

    def _assert_xlsx_and_pdf(self, key, **params):
        resp = self.client.get(self._url(key, format="xlsx", **params))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], XLSX_CT)
        self.assertIn(key, resp["Content-Disposition"])
        n_xlsx = self._last_log().dettaglio.get("n_righe")

        resp = self.client.get(self._url(key, format="pdf", **params))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF"))
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), n_xlsx)
        return n_xlsx

    # -- registry -------------------------------------------------------------
    def test_tutte_le_spec_formazione_sono_registrate(self):
        for key in FORMAZIONE_KEYS:
            self.assertIn(key, EXPORT_SPECS, f"spec '{key}' non registrata")
            self.assertTrue(callable(EXPORT_SPECS[key].permission), f"spec '{key}' senza gate ACL")

    def test_ogni_dataset_riempie_tutte_le_colonne_dichiarate(self):
        from django.test import RequestFactory

        request = RequestFactory().get("/anagrafica/esporta/x/")
        request.user = self.admin
        for key in FORMAZIONE_KEYS:
            spec = EXPORT_SPECS[key]
            rows = spec.dataset(request, "full")
            self.assertTrue(rows, f"dataset '{key}' vuoto sui dati di test")
            accessors = {accessor for _label, accessor in spec.columns}
            for row in rows:
                self.assertEqual(accessors - set(row), set(), f"colonne mancanti in '{key}'")

    # -- corsi ----------------------------------------------------------------
    def test_export_formazione_corsi(self):
        self.assertEqual(self._assert_xlsx_and_pdf("formazione_corsi", scope="full"), 2)

    def test_formazione_corsi_filtri_querystring(self):
        self.client.get(self._url("formazione_corsi", format="xlsx", q="antinc"))
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), 1)
        self.client.get(self._url("formazione_corsi", format="xlsx", stato="ATTIVO"))
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), 1)
        self.client.get(self._url("formazione_corsi", format="xlsx", obbligatorio="1"))
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), 1)
        self.client.get(self._url("formazione_corsi", format="xlsx", piano=self.piano_it.pk))
        log = self._last_log()
        self.assertEqual(log.dettaglio.get("n_righe"), 1)
        self.assertIn("Piano Informatica", log.dettaglio.get("filtri", ""))

    # -- sessioni -------------------------------------------------------------
    def test_export_formazione_sessioni(self):
        self.assertEqual(self._assert_xlsx_and_pdf("formazione_sessioni", scope="full"), 2)

    def test_formazione_sessioni_filtri_querystring(self):
        self.client.get(self._url("formazione_sessioni", format="xlsx", anno="2026"))
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), 1)
        self.client.get(self._url("formazione_sessioni", format="xlsx", stato="PIANIFICATA"))
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), 1)
        self.client.get(self._url("formazione_sessioni", format="xlsx", corso=self.corso_a.pk))
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), 1)
        self.client.get(self._url("formazione_sessioni", format="xlsx", q="aula"))
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), 1)

    # -- piani ----------------------------------------------------------------
    def test_export_formazione_piani(self):
        self.assertEqual(self._assert_xlsx_and_pdf("formazione_piani", scope="full"), 2)

    def test_formazione_piani_filtri_querystring(self):
        self.client.get(self._url("formazione_piani", format="xlsx", stato="ATTIVO"))
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), 1)
        self.client.get(self._url("formazione_piani", format="xlsx", categoria="FACOLTATIVA"))
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), 1)

    # -- istruttori -----------------------------------------------------------
    def test_export_formazione_istruttori(self):
        self.assertEqual(self._assert_xlsx_and_pdf("formazione_istruttori", scope="full"), 2)

    def test_formazione_istruttori_filtri_querystring(self):
        self.client.get(self._url("formazione_istruttori", format="xlsx", tipo="INTERNO"))
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), 1)
        self.client.get(self._url("formazione_istruttori", format="xlsx", q="docente"))
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), 1)

    # -- scadenzario ----------------------------------------------------------
    def test_export_formazione_scadenzario(self):
        # scope=full → tutte le scadenze (anche i VALIDO, esclusi dal default).
        self.assertEqual(self._assert_xlsx_and_pdf("formazione_scadenzario", scope="full"), 2)

    def test_formazione_scadenzario_default_esclude_i_validi(self):
        self.client.get(self._url("formazione_scadenzario", format="xlsx"))
        log = self._last_log()
        self.assertEqual(log.dettaglio.get("n_righe"), 1)  # solo lo SCADUTO
        self.client.get(self._url("formazione_scadenzario", format="xlsx", stato="VALIDO"))
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), 1)
        self.client.get(self._url("formazione_scadenzario", format="xlsx", corso=self.corso_a.pk))
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), 1)
        self.client.get(self._url("formazione_scadenzario", format="xlsx", q="bianchi", stato="VALIDO"))
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), 1)
        self.client.get(self._url("formazione_scadenzario", format="xlsx", q="bianchi"))
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), 0)

    def test_scadenzario_riporta_il_nome_del_dipendente(self):
        from django.test import RequestFactory

        request = RequestFactory().get("/anagrafica/esporta/formazione_scadenzario/")
        request.user = self.admin
        rows = EXPORT_SPECS["formazione_scadenzario"].dataset(request, "filtered")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dipendente"], "Rossi Test Luca")
        self.assertIn("C-ANTINC", rows[0]["corso"])
        self.assertEqual(rows[0]["obbligatorio"], "Si")

    # -- rischi ---------------------------------------------------------------
    def test_export_fattori_rischio(self):
        self.assertEqual(self._assert_xlsx_and_pdf("fattori_rischio"), 2)

    def test_export_categorie_corso(self):
        self.assertEqual(self._assert_xlsx_and_pdf("categorie_corso"), 1)

    def test_categorie_corso_elenca_i_fattori_collegati(self):
        from django.test import RequestFactory

        request = RequestFactory().get("/anagrafica/esporta/categorie_corso/")
        request.user = self.admin
        rows = EXPORT_SPECS["categorie_corso"].dataset(request, "filtered")
        self.assertEqual(rows[0]["fattori"], "F-RUM")

    def test_export_esposizioni_rischio(self):
        self.assertEqual(self._assert_xlsx_and_pdf("esposizioni_rischio"), 1)
