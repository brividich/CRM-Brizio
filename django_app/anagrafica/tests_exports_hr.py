"""Test degli export «Cataloghi / HR» di anagrafica (vedi `anagrafica/exports_hr.py`).

Un test per chiave registrata: la spec esiste nel registry e
``build_export_response`` produce XLSX e PDF con le righe attese.
Tutti i dati sono sintetici.
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from anagrafica.exports import EXPORT_SPECS
from anagrafica.models import (
    AreaAziendale,
    DipendenteAnagraficaCivile,
    DipendenteRuoloOperativo,
    ImportazioneCedolini,
    ImportazioneRetributiva,
    Reparto,
    RuoloAziendale,
    RuoloOperativo,
    SaldoCedolino,
    TipoVisitaMedica,
    VisitaMedica,
    VoceRetributiva,
)
# Riuso l'helper che crea la tabella legacy `anagrafica_dipendenti` (unmanaged).
from anagrafica.tests import _ensure_anagrafica_table
from core.legacy_models import AnagraficaDipendente
from core.models import AuditLog

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

User = get_user_model()

CF_ROSSI = "RSSMRA80A01H501U"
CF_BIANCHI = "BNCLRA85B41H501K"


class ExportHRTestCase(TestCase):
    """Dataset sintetico condiviso da tutti gli export dell'area Cataloghi/HR."""

    @classmethod
    def setUpClass(cls):
        # La tabella legacy va creata PRIMA di setUpTestData (l'helper fa DROP+CREATE).
        _ensure_anagrafica_table()
        super().setUpClass()

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("admin_export_hr", "admin-hr@example.invalid", "x")

        # -- anagrafica legacy (solo nomi, dati sintetici) --------------------
        cls.dip_rossi = AnagraficaDipendente.objects.create(
            nome="Mario", cognome="Rossi", reparto="Produzione"
        )
        cls.dip_bianchi = AnagraficaDipendente.objects.create(
            nome="Laura", cognome="Bianchi", reparto="Ufficio"
        )
        DipendenteAnagraficaCivile.objects.create(
            legacy_anagrafica_id=cls.dip_rossi.id, codice_fiscale=CF_ROSSI, genere="M"
        )
        DipendenteAnagraficaCivile.objects.create(
            legacy_anagrafica_id=cls.dip_bianchi.id, codice_fiscale=CF_BIANCHI, genere="F"
        )

        # -- cataloghi --------------------------------------------------------
        cls.reparto = Reparto.objects.create(
            nome="Produzione", descrizione="Reparto produttivo",
            caporeparto_legacy_id=cls.dip_rossi.id,
        )
        AreaAziendale.objects.create(nome="IN1", reparto=cls.reparto,
                                     responsabile_legacy_id=cls.dip_bianchi.id)
        AreaAziendale.objects.create(nome="Area orfana")  # senza reparto

        RuoloAziendale.objects.create(nome="Responsabile qualità", descrizione="RQ")
        RuoloAziendale.objects.create(nome="Addetto amministrazione", is_active=False)

        cls.ruolo_op = RuoloOperativo.objects.create(nome="Preposto")
        RuoloOperativo.objects.create(nome="RLS")
        DipendenteRuoloOperativo.objects.create(
            legacy_anagrafica_id=cls.dip_rossi.id, ruolo=cls.ruolo_op
        )

        # -- ratei (2 periodi × 2 dipendenti) ---------------------------------
        imp = ImportazioneCedolini.objects.create(data_competenza=date(2026, 5, 31))
        for cf, lid in ((CF_ROSSI, cls.dip_rossi.id), (CF_BIANCHI, cls.dip_bianchi.id)):
            SaldoCedolino.objects.create(
                importazione=imp, tax_code=cf, legacy_anagrafica_id=lid,
                data_competenza=date(2026, 5, 31),
                anzianita_anni=3, anzianita_mesi=2,
                ferie_residui=40, rol_residui=8, ex_fest_residui=4,
            )
        SaldoCedolino.objects.create(
            importazione=imp, tax_code=CF_ROSSI, legacy_anagrafica_id=cls.dip_rossi.id,
            data_competenza=date(2026, 4, 30), ferie_residui=32,
        )

        # -- retribuzioni (1 dipendente × 1 mese × 2 voci) ---------------------
        imp_retr = ImportazioneRetributiva.objects.create(data_competenza=date(2026, 5, 1))
        for key, label, cat, importo in (
            ("paga_base", "Paga base", VoceRetributiva.CAT_FISSO, 1500),
            ("straordinari", "Straordinari", VoceRetributiva.CAT_VARIABILE, 120),
        ):
            VoceRetributiva.objects.create(
                importazione=imp_retr, tax_code=CF_ROSSI,
                legacy_anagrafica_id=cls.dip_rossi.id,
                data_competenza=date(2026, 5, 1),
                pay_item=label, pay_item_key=key, categoria=cat, importo=importo,
            )

        # -- visite mediche ---------------------------------------------------
        oggi = timezone.localdate()
        cls.tipo_visita = TipoVisitaMedica.objects.create(
            nome="Visita periodica", durata_mesi=12, obbligatoria=True
        )
        cls.tipo_visita.ruoli_operativi.add(cls.ruolo_op)
        # scaduta ieri → compare nella tabella scadenze
        VisitaMedica.objects.create(
            legacy_anagrafica_id=cls.dip_rossi.id, tipo=cls.tipo_visita,
            data_svolgimento=oggi - timedelta(days=366),
            data_scadenza=oggi - timedelta(days=1),
        )
        # valida a lungo → fuori dalla finestra 60 giorni
        VisitaMedica.objects.create(
            legacy_anagrafica_id=cls.dip_bianchi.id, tipo=cls.tipo_visita,
            data_svolgimento=oggi, data_scadenza=oggi + timedelta(days=300),
        )

    # -- helper ---------------------------------------------------------------
    def _url(self, key, **params):
        url = reverse("anagrafica:export", args=[key])
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        return url

    def _download(self, key, fmt="xlsx", **params):
        self.client.force_login(self.admin)
        resp = self.client.get(self._url(key, format=fmt, **params))
        self.assertEqual(resp.status_code, 200)
        if fmt == "pdf":
            self.assertEqual(resp["Content-Type"], "application/pdf")
            self.assertTrue(resp.content.startswith(b"%PDF"))
        else:
            self.assertEqual(resp["Content-Type"], XLSX_CT)
        return resp

    def _last_log(self):
        return AuditLog.objects.filter(azione="export").latest("id")

    def _rows(self, key, scope="full", **get):
        """Righe prodotte dal dataset della spec (senza passare dall'HTTP)."""
        from django.test import RequestFactory

        spec = EXPORT_SPECS[key]
        request = RequestFactory().get(f"/anagrafica/esporta/{key}/", data=get)
        request.user = self.admin
        return list(spec.dataset(request, scope))

    def _assert_columns_filled(self, key, rows):
        spec = EXPORT_SPECS[key]
        accessors = {accessor for _label, accessor in spec.columns}
        for row in rows:
            self.assertEqual(accessors - set(row), set(), f"colonne mancanti in '{key}'")

    def _assert_spec_ok(self, key, expected_rows, **get):
        """Spec registrata + XLSX/PDF generati + n. righe atteso."""
        self.assertIn(key, EXPORT_SPECS)
        self.assertTrue(callable(EXPORT_SPECS[key].permission))

        rows = self._rows(key, scope="filtered" if get else "full", **get)
        self.assertEqual(len(rows), expected_rows)
        self._assert_columns_filled(key, rows)

        self._download(key, fmt="xlsx", **get)
        self.assertEqual(self._last_log().dettaglio.get("n_righe"), expected_rows)
        self._download(key, fmt="pdf", **get)
        log = self._last_log()
        self.assertEqual(log.dettaglio.get("lista"), key)
        self.assertEqual(log.dettaglio.get("n_righe"), expected_rows)


class CataloghiExportTests(ExportHRTestCase):
    def test_aree(self):
        self._assert_spec_ok("aree", 2)
        rows = self._rows("aree")
        by_name = {r["nome"]: r for r in rows}
        self.assertEqual(by_name["IN1"]["reparto"], "Produzione")
        self.assertEqual(by_name["IN1"]["responsabile"], "Bianchi Laura")
        self.assertEqual(by_name["Area orfana"]["reparto"], "")

    def test_reparti(self):
        self._assert_spec_ok("reparti", 1)
        row = self._rows("reparti")[0]
        self.assertEqual(row["nome"], "Produzione")
        self.assertEqual(row["caporeparto"], "Rossi Mario")
        self.assertEqual(row["aree"], "IN1")
        self.assertEqual(row["n_aree"], 1)

    def test_ruoli_aziendali(self):
        self._assert_spec_ok("ruoli_aziendali", 2)
        stati = {r["nome"]: r["stato"] for r in self._rows("ruoli_aziendali")}
        self.assertEqual(stati["Responsabile qualità"], "Attivo")
        self.assertEqual(stati["Addetto amministrazione"], "Inattivo")

    def test_ruoli_operativi(self):
        self._assert_spec_ok("ruoli_operativi", 2)
        assegnati = {r["nome"]: r["n_assegnati"] for r in self._rows("ruoli_operativi")}
        self.assertEqual(assegnati["Preposto"], 1)
        self.assertEqual(assegnati["RLS"], 0)


class RateiExportTests(ExportHRTestCase):
    def test_ratei_full(self):
        self._assert_spec_ok("ratei", 3)
        nomi = {r["dipendente"] for r in self._rows("ratei")}
        self.assertIn("Rossi Mario", nomi)
        self.assertIn("Bianchi Laura", nomi)

    def test_ratei_filtro_periodo(self):
        self._assert_spec_ok("ratei", 2, periodo="2026-05-31")

    def test_ratei_filtro_dipendente(self):
        self._assert_spec_ok("ratei", 2, dipendente=CF_ROSSI)

    def test_ratei_filtro_reparto(self):
        rows = self._rows("ratei", scope="filtered", reparto="Ufficio")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["dipendente"], "Bianchi Laura")

    def test_ratei_scope_full_ignora_i_filtri(self):
        self.assertEqual(len(self._rows("ratei", scope="full", dipendente=CF_ROSSI)), 3)


class RetribuzioniExportTests(ExportHRTestCase):
    def test_retribuzioni_globale(self):
        # 1 dipendente × 1 mese × 2 voci valorizzate → 2 righe (formato lungo).
        self._assert_spec_ok("retribuzioni_globale", 2)
        rows = self._rows("retribuzioni_globale")
        voci = {r["voce"]: r for r in rows}
        self.assertEqual(voci["Paga base"]["dipendente"], "Rossi Mario")
        self.assertEqual(voci["Paga base"]["periodo"], "05-2026")
        self.assertEqual(voci["Straordinari"]["categoria"], "Elementi Variabili")

    def test_retribuzioni_filtro_dipendente_vuoto(self):
        rows = self._rows("retribuzioni_globale", scope="filtered", dipendente=CF_BIANCHI)
        self.assertEqual(rows, [])


class VisiteMedicheExportTests(ExportHRTestCase):
    def test_visite_mediche_scadenze(self):
        # Solo la visita scaduta rientra nella finestra (≤60g); l'altra no.
        self._assert_spec_ok("visite_mediche", 1)
        row = self._rows("visite_mediche")[0]
        self.assertEqual(row["dipendente"], "Rossi Mario")
        self.assertEqual(row["tipo"], "Visita periodica")
        self.assertTrue(row["stato"].startswith("Scaduta"))
        # GDPR: nessun esito/giudizio sanitario tra le colonne esportate.
        accessors = {a for _l, a in EXPORT_SPECS["visite_mediche"].columns}
        self.assertNotIn("esito", accessors)
        self.assertNotIn("prescrizioni", accessors)

    def test_visite_mediche_filtro_prossimo_mese(self):
        rows = self._rows("visite_mediche", scope="filtered", scad="prossimo_mese")
        self.assertEqual(rows, [])

    def test_visite_mediche_copertura(self):
        # Il catalogo tipi contiene anche le tipologie seed delle migration:
        # l'export deve elencarle tutte (una riga per tipologia attiva).
        attesi = TipoVisitaMedica.objects.filter(is_active=True).count()
        self._assert_spec_ok("visite_mediche_copertura", attesi)
        rows = {r["tipologia"]: r for r in self._rows("visite_mediche_copertura")}
        row = rows["Visita periodica"]
        self.assertEqual(row["periodicita"], 12)
        self.assertEqual(row["obbligatoria"], "Si")
        self.assertEqual(row["ruoli"], "Preposto")
        self.assertEqual(row["richiesti"], 1)   # Rossi ha il ruolo Preposto
        self.assertEqual(row["coperti"], 0)     # ma la sua visita è scaduta
        self.assertEqual(row["mancanti"], 1)
        self.assertEqual(row["scadute"], 1)
        self.assertEqual(row["valide"], 1)      # la visita di Bianchi è valida
