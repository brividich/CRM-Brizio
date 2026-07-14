"""Export tabellari (PDF/Excel) delle liste dell'area «Persone» di anagrafica.

Un test per chiave registrata: la spec esiste nel registry, l'endpoint unico
produce xlsx e pdf, e le righe/filtri sono quelli della lista di origine.
Dati sintetici (nessun dato reale): l'anagrafica legacy è una tabella grezza
creata dall'helper condiviso `_ensure_anagrafica_table`.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.models import AuditLog

from .exports import EXPORT_SPECS
from .models import (
    CartellaDocumentoDipendente,
    DipendenteAnagraficaAziendale,
    DipendenteQualifica,
    DocumentoDipendente,
    OnboardingPratica,
    OnboardingTask,
    Reparto,
    TipoQualifica,
)
from .tests import _ensure_anagrafica_table

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

User = get_user_model()

PERSONE_KEYS = [
    "dipendenti",
    "ex_dipendenti",
    "documenti",
    "onboarding",
    "scadenzario",
    "conformita",
    "organigramma",
]


def _insert_dipendente(legacy_id: int, nome: str, cognome: str, **extra) -> int:
    """Inserisce una riga sintetica in `anagrafica_dipendenti` (tabella legacy)."""
    cols = {
        "id": legacy_id,
        "nome": nome,
        "cognome": cognome,
        "aliasusername": extra.get("aliasusername", ""),
        "mansione": extra.get("mansione", ""),
        "reparto": extra.get("reparto", ""),
        "matricola": extra.get("matricola", ""),
        "attivo": extra.get("attivo", 1),
        "email_notifica": extra.get("email_notifica", ""),
    }
    names = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO anagrafica_dipendenti ({names}) VALUES ({placeholders})",
            list(cols.values()),
        )
    return legacy_id


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ExportPersoneTests(TestCase):
    """L'area «Persone»: 7 liste, 7 spec, xlsx + pdf + filtri della querystring."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            "admin_persone", "admin_persone@example.invalid", "x"
        )

        # ── Anagrafica sintetica ────────────────────────────────────────────
        # 2 in forza (Rossi in PRODUZIONE, Bianchi in UFFICIO) + 1 cessato.
        cls.id_rossi = _insert_dipendente(
            5001, "Mario", "Rossi",
            aliasusername="m.rossi", mansione="Saldatore", reparto="PRODUZIONE",
            matricola="M001", email_notifica="m.rossi@example.invalid",
        )
        cls.id_bianchi = _insert_dipendente(
            5002, "Anna", "Bianchi",
            aliasusername="a.bianchi", mansione="Impiegata", reparto="UFFICIO",
            matricola="M002", email_notifica="a.bianchi@example.invalid",
        )
        cls.id_ex = _insert_dipendente(
            5003, "Carlo", "Verdi",
            aliasusername="c.verdi", mansione="Magazziniere", reparto="LOGISTICA",
            matricola="M003", attivo=0,
        )
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=cls.id_ex,
            data_cessazione=date(2026, 1, 31),
            data_assunzione_ultima=date(2020, 3, 1),
        )

        # ── Organigramma: un reparto a catalogo con capo ────────────────────
        Reparto.objects.create(nome="PRODUZIONE", caporeparto_legacy_id=cls.id_rossi)

        # ── Documenti ───────────────────────────────────────────────────────
        cls.cartella = CartellaDocumentoDipendente.objects.create(nome="Contratti")
        doc = DocumentoDipendente(
            legacy_anagrafica_id=cls.id_rossi,
            tipo=DocumentoDipendente.Tipo.MANUALE,
            cartella=cls.cartella,
            nome_originale="contratto_sintetico.pdf",
            descrizione="Documento di test",
        )
        doc.file.save("contratto_sintetico.pdf", ContentFile(b"%PDF-fake"), save=False)
        doc.save()
        cls.doc = doc

        # ── Onboarding ──────────────────────────────────────────────────────
        pratica = OnboardingPratica.objects.create(
            legacy_anagrafica_id=cls.id_bianchi,
            dipendente_nome="Bianchi Anna",
            reparto="UFFICIO",
            data_assunzione=date(2026, 6, 1),
            stato=OnboardingPratica.STATO_IN_CORSO,
        )
        OnboardingTask.objects.create(
            pratica=pratica, codice="ACCOUNT", titolo="Creazione account",
            stato=OnboardingTask.STATO_COMPLETATO,
        )
        OnboardingTask.objects.create(
            pratica=pratica, codice="BADGE", titolo="Consegna badge",
            stato=OnboardingTask.STATO_DA_FARE,
        )
        OnboardingPratica.objects.create(
            legacy_anagrafica_id=cls.id_rossi,
            dipendente_nome="Rossi Mario",
            reparto="PRODUZIONE",
            stato=OnboardingPratica.STATO_CHIUSA,
        )

        # ── Scadenzario: una qualifica scaduta + una in scadenza ────────────
        tipo_q = TipoQualifica.objects.create(nome="Patentino carrello")
        oggi = date.today()
        DipendenteQualifica.objects.create(
            legacy_anagrafica_id=cls.id_rossi, tipo=tipo_q,
            data_scadenza=oggi - timedelta(days=10),
        )
        DipendenteQualifica.objects.create(
            legacy_anagrafica_id=cls.id_bianchi, tipo=tipo_q,
            data_scadenza=oggi + timedelta(days=20),
        )

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

    def _rows(self, key, scope="full", **get_params):
        """Righe prodotte dal dataset della spec (senza passare dall'endpoint)."""
        spec = EXPORT_SPECS[key]
        qs = "&".join(f"{k}={v}" for k, v in get_params.items())
        request = RequestFactory().get(f"/anagrafica/esporta/{key}/?{qs}")
        request.user = self.admin
        return spec.dataset(request, scope)

    def _assert_xlsx_and_pdf(self, key, **params):
        xlsx = self.client.get(self._url(key, format="xlsx", **params))
        self.assertEqual(xlsx.status_code, 200)
        self.assertEqual(xlsx["Content-Type"], XLSX_CT)
        self.assertIn(key, xlsx["Content-Disposition"])
        n_righe = self._last_log().dettaglio.get("n_righe")

        pdf = self.client.get(self._url(key, format="pdf", **params))
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))
        return n_righe

    # -- registry -------------------------------------------------------------
    def test_tutte_le_key_persone_sono_registrate_con_gate(self):
        for key in PERSONE_KEYS:
            self.assertIn(key, EXPORT_SPECS, f"spec '{key}' non registrata")
            self.assertTrue(callable(EXPORT_SPECS[key].permission), f"spec '{key}' senza gate")

    def test_ogni_dataset_riempie_tutte_le_colonne_dichiarate(self):
        for key in PERSONE_KEYS:
            spec = EXPORT_SPECS[key]
            accessors = {accessor for _label, accessor in spec.columns}
            rows = self._rows(key)
            self.assertTrue(rows, f"dataset '{key}' vuoto: il test non verifica nulla")
            for row in rows:
                self.assertEqual(accessors - set(row), set(), f"colonne mancanti in '{key}'")

    # -- dipendenti -----------------------------------------------------------
    def test_export_dipendenti(self):
        n = self._assert_xlsx_and_pdf("dipendenti", scope="filtered")
        self.assertEqual(n, 2)  # il cessato non compare mai in questa lista
        nomi = [r["dipendente"] for r in self._rows("dipendenti")]
        self.assertEqual(nomi, ["Bianchi Anna", "Rossi Mario"])
        self.assertNotIn("Verdi Carlo", nomi)

    def test_dipendenti_filtri_querystring(self):
        rows = self._rows("dipendenti", scope="filtered", q="rossi")
        self.assertEqual([r["dipendente"] for r in rows], ["Rossi Mario"])
        rows = self._rows("dipendenti", scope="filtered", reparto="UFFICIO")
        self.assertEqual([r["dipendente"] for r in rows], ["Bianchi Anna"])
        # scope=full ignora la querystring
        self.assertEqual(len(self._rows("dipendenti", scope="full", q="rossi")), 2)

    # -- ex dipendenti --------------------------------------------------------
    def test_export_ex_dipendenti(self):
        n = self._assert_xlsx_and_pdf("ex_dipendenti", scope="filtered")
        self.assertEqual(n, 1)
        row = self._rows("ex_dipendenti")[0]
        self.assertEqual(row["dipendente"], "Verdi Carlo")
        self.assertEqual(row["data_cessazione"], "31-01-2026")
        self.assertEqual(row["matricola"], "M003")

    def test_ex_dipendenti_filtro_q(self):
        self.assertEqual(len(self._rows("ex_dipendenti", scope="filtered", q="verdi")), 1)
        self.assertEqual(len(self._rows("ex_dipendenti", scope="filtered", q="rossi")), 0)

    # -- documenti ------------------------------------------------------------
    def test_export_documenti(self):
        n = self._assert_xlsx_and_pdf("documenti", scope="filtered")
        self.assertEqual(n, 1)
        row = self._rows("documenti")[0]
        self.assertEqual(row["dipendente"], "Rossi Mario")
        self.assertEqual(row["cartella"], "Contratti")
        self.assertEqual(row["file"], "contratto_sintetico.pdf")

    def test_documenti_filtri_querystring(self):
        self.assertEqual(len(self._rows("documenti", scope="filtered", q="contratto")), 1)
        self.assertEqual(len(self._rows("documenti", scope="filtered", q="inesistente")), 0)
        self.assertEqual(
            len(self._rows("documenti", scope="filtered", cartella=str(self.cartella.pk))), 1
        )
        self.assertEqual(len(self._rows("documenti", scope="filtered", cartella="__nessuna__")), 0)

    # -- onboarding -----------------------------------------------------------
    def test_export_onboarding(self):
        n = self._assert_xlsx_and_pdf("onboarding", scope="filtered")
        self.assertEqual(n, 2)
        rows = {r["dipendente"]: r for r in self._rows("onboarding")}
        self.assertEqual(rows["Bianchi Anna"]["stato"], "In corso")
        self.assertEqual(rows["Bianchi Anna"]["avanzamento"], "1/2 completati")
        self.assertEqual(rows["Bianchi Anna"]["data_assunzione"], "01-06-2026")

    def test_onboarding_filtro_stato(self):
        rows = self._rows("onboarding", scope="filtered", stato="IN_CORSO")
        self.assertEqual([r["dipendente"] for r in rows], ["Bianchi Anna"])
        self.assertEqual(len(self._rows("onboarding", scope="full", stato="IN_CORSO")), 2)

    # -- scadenzario ----------------------------------------------------------
    def test_export_scadenzario(self):
        n = self._assert_xlsx_and_pdf("scadenzario", scope="filtered")
        self.assertEqual(n, 2)
        rows = self._rows("scadenzario")
        # Ordinamento per urgenza: prima la scaduta.
        self.assertEqual(rows[0]["dipendente"], "Rossi Mario")
        self.assertEqual(rows[0]["stato"], "Scaduta")
        self.assertEqual(rows[0]["tipo"], "Qualifica")
        self.assertEqual(rows[0]["descrizione"], "Patentino carrello")

    def test_scadenzario_filtri_querystring(self):
        rows = self._rows("scadenzario", scope="filtered", stato="scaduta")
        self.assertEqual([r["dipendente"] for r in rows], ["Rossi Mario"])
        rows = self._rows("scadenzario", scope="filtered", reparto="UFFICIO")
        self.assertEqual([r["dipendente"] for r in rows], ["Bianchi Anna"])
        rows = self._rows("scadenzario", scope="filtered", tipo="contratto")
        self.assertEqual(rows, [])

    # -- conformita -----------------------------------------------------------
    def test_export_conformita(self):
        n = self._assert_xlsx_and_pdf("conformita", scope="filtered")
        self.assertEqual(n, 2)  # solo i dipendenti attivi
        rows = {r["dipendente"]: r for r in self._rows("conformita")}
        self.assertIn("Rossi Mario", rows)
        self.assertEqual(rows["Rossi Mario"]["reparto"], "PRODUZIONE")
        self.assertEqual(rows["Rossi Mario"]["mansione"], "Saldatore")
        self.assertTrue(rows["Rossi Mario"]["conformita"])

    def test_conformita_filtro_reparto(self):
        rows = self._rows("conformita", scope="filtered", reparto="PRODUZIONE")
        self.assertEqual([r["dipendente"] for r in rows], ["Rossi Mario"])

    # -- organigramma ---------------------------------------------------------
    def test_export_organigramma(self):
        n = self._assert_xlsx_and_pdf("organigramma", scope="filtered")
        self.assertEqual(n, 2)  # capo PRODUZIONE + 1 non mappato (UFFICIO non a catalogo)
        rows = {r["dipendente"]: r for r in self._rows("organigramma")}
        self.assertEqual(rows["Rossi Mario"]["ruolo"], "Caporeparto")
        self.assertEqual(rows["Rossi Mario"]["reparto"], "PRODUZIONE")
        self.assertEqual(rows["Rossi Mario"]["responsabile"], "Rossi Mario")
        self.assertEqual(rows["Bianchi Anna"]["ruolo"], "Reparto non a catalogo")

    def test_organigramma_filtro_reparto(self):
        rows = self._rows("organigramma", scope="filtered", reparto="PRODUZIONE")
        self.assertEqual([r["dipendente"] for r in rows], ["Rossi Mario"])

    # -- audit ----------------------------------------------------------------
    def test_audit_scritto_per_ogni_lista_persone(self):
        for key in PERSONE_KEYS:
            self.client.get(self._url(key, format="xlsx"))
            log = self._last_log()
            self.assertEqual(log.modulo, "anagrafica")
            self.assertEqual(log.dettaglio.get("lista"), key)
            self.assertEqual(log.dettaglio.get("formato"), "xlsx")


class ExportDocumentiCartellaRiservataTests(TestCase):
    """Il NOME di una cartella riservata (`solo_admin`) non deve trapelare.

    Un non-superuser che passa `?cartella=<id riservata>` ottiene gia' 0 righe
    (la cartella e' esclusa dal queryset), ma non deve ricevere in regalo la
    denominazione della cartella nell'etichetta dei filtri dell'export.
    """

    @classmethod
    def setUpTestData(cls):
        from anagrafica.models import CartellaDocumentoDipendente

        User = get_user_model()
        cls.riservata = CartellaDocumentoDipendente.objects.create(
            nome="Provvedimenti disciplinari", solo_admin=True,
        )
        cls.admin = User.objects.create_superuser(
            "exp-doc-admin", "exp-doc-admin@test.local", "pass12345",
        )
        cls.utente = User.objects.create_user(
            "exp-doc-user", "exp-doc-user@test.local", "pass12345",
        )

    def _label(self, user):
        from anagrafica.exports_persone import _documenti_filters

        request = RequestFactory().get(
            f"/anagrafica/esporta/documenti/?cartella={self.riservata.pk}"
        )
        request.user = user
        return _documenti_filters(request)

    def test_reserved_cartella_name_not_disclosed_to_non_superuser(self):
        label = self._label(self.utente)
        self.assertNotIn("Provvedimenti disciplinari", label)
        self.assertIn(str(self.riservata.pk), label)

    def test_superuser_still_sees_the_name(self):
        self.assertIn("Provvedimenti disciplinari", self._label(self.admin))
