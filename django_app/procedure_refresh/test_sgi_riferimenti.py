"""Test fase A2 database SGI: grafo dei riferimenti e collegamento ai processi.
Solo testi sintetici; i codici seguono il formato SGI ma i documenti sono inventati."""

from __future__ import annotations

import io
from datetime import date
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from procedure_refresh.models import (
    DocumentType,
    ProcedureDocument,
    ProcedureRevision,
    SgiDocumentoProcesso,
    SgiRiferimento,
    SgiTestoEstratto,
    SourceType,
)
from procedure_refresh.sgi_riferimenti import (
    Catalogo,
    codici_citati,
    estrai_citazioni,
    norme_citate,
    ricostruisci,
)


def _rev(code: str, title: str = "Documento sintetico") -> ProcedureRevision:
    doc = ProcedureDocument.objects.create(code=code, title=title, document_type=DocumentType.ALTRO)
    return ProcedureRevision.objects.create(
        document=doc, revision_code="1", revision_date=date(2026, 1, 1), effective_date=date(2026, 1, 1),
        source_type=SourceType.FILESERVER, source_path="", file_name=f"{code}.pdf", file_hash="h", is_current=True,
    )


def _codici(testo: str, proprio: str = "") -> dict[str, int]:
    out: dict[str, int] = {}
    for c in estrai_citazioni(testo, proprio):
        out[c.codice] = out.get(c.codice, 0) + c.occorrenze
    return out


class EstrazioneTests(SimpleTestCase):
    def test_citazioni_multiple_allegati_sottonumeri(self):
        testo = ("1. Scopo\nVedi MT CN 06 e il modulo MOD.093; per i dettagli MT CN 06.\n"
                 "2. Riferimenti\nIDOR CN 01 Allegato A, MT CN 125_10, MTSI CN 11.")
        self.assertEqual(_codici(testo), {"MT CN 06": 2, "MOD.093": 1, "IDOR CN 01 Allegato A": 1,
                                          "MT CN 125_10": 1, "MTSI CN 11": 1})

    def test_mod_con_spazio_normalizzato(self):
        self.assertEqual(codici_citati("compilare il MOD. 093 entro fine mese"), ["MOD.093"])

    def test_codice_in_tabella_pipe(self):
        testo = "| Codice | Titolo |\n| --- | --- |\n| MOD.093 | Registro sintetico |\n| MT CN 06 | Procedura |"
        self.assertEqual(_codici(testo), {"MOD.093": 1, "MT CN 06": 1})

    def test_codice_spezzato_a_fine_riga(self):
        testo = "Le registrazioni seguono la procedura MT CN\n06 e il modulo MOD.\n093."
        self.assertEqual(_codici(testo), {"MT CN 06": 1, "MOD.093": 1})

    def test_autocitazione_esclusa(self):
        testo = "Questa procedura MT CN 06 rimanda a MOD.093. La MT CN 06 si applica a tutti."
        self.assertEqual(_codici(testo, "MT CN 06"), {"MOD.093": 1})

    def test_cartiglio_ripetuto_escluso(self):
        cartiglio = "MOD.093 Rev.4 — Registro sintetico — collegato a MT CN 06"
        testo = "\n".join([cartiglio, "Pagina uno: vedi MT CN 12.", cartiglio, "Pagina due.", cartiglio, "Fine."])
        self.assertEqual(_codici(testo, "MOD.093"), {"MT CN 12": 1})

    def test_niente_falsi_positivi(self):
        testo = "superficie 50 mq, pg. 3, io 2 volte, FORMAT 12, ISO 9001:2015, UNI EN 1090-2, AS9100 e AS 9102."
        self.assertEqual(codici_citati(testo), [])

    def test_norme_esterne_contate_a_parte(self):
        norme = norme_citate("Secondo ISO 9001:2015, UNI EN ISO 9001, EN 9100, AS 9102 e ASTM E 1444; ancora ISO 9001.")
        self.assertEqual(norme["ISO 9001"], 2)
        self.assertEqual(norme["UNI EN ISO 9001"], 1)
        self.assertEqual(norme["AS 9102"], 1)
        self.assertEqual(norme["ASTM 1444"], 1)
        self.assertEqual(codici_citati("Secondo ISO 9001 e UNI EN 1090"), [])

    def test_sezione_registrata(self):
        testo = "1. Scopo generale\nnulla\n2. Riferimenti normativi\nvedi MOD.093"
        (c,) = estrai_citazioni(testo)
        self.assertEqual(c.sezione, "§2 Riferimenti normativi")


class RisoluzioneTests(TestCase):
    def setUp(self):
        self.mt06 = _rev("MT CN 06").document
        self.mod93 = _rev("MOD.093").document
        self.idor = _rev("IDOR CN 01").document
        self.isms = _rev("IDOR CN 02 ISMS").document  # codice disambiguato dall'import

    def test_esatto_normalizzato_disambiguato_allegato(self):
        cat = Catalogo()
        self.assertEqual(cat.risolvi("MOD.093"), self.mod93)
        self.assertEqual(cat.risolvi("MOD 93"), self.mod93)
        self.assertEqual(cat.risolvi("MT CN 6"), self.mt06)
        self.assertEqual(cat.risolvi("IDOR CN 02"), self.isms)
        self.assertEqual(cat.risolvi("IDOR CN 01 Allegato A"), self.idor)
        self.assertIsNone(cat.risolvi("MT CN 999"))

    def test_citazione_abbreviata_senza_cn(self):
        cat = Catalogo()
        self.assertEqual(cat.risolvi("MT.6"), self.mt06)
        self.assertEqual(cat.risolvi("MT 06"), self.mt06)
        self.assertEqual(codici_citati("vedi MT.6 e MT 06"), ["MT.6", "MT 06"])
        self.assertIsNone(cat.risolvi("MT 999"))
        self.assertIsNone(cat.risolvi("MOD 06"))  # MOD non ha la famiglia CN

    def test_ricostruisci_in_transazione_e_inesistenti(self):
        rev = _rev("MT CN 77").document.revisions.get()
        testo = "1. Scopo\nvedi MOD.093 e MT CN 999\n2. Altro\nancora MOD.093 e MOD.093"
        self.assertEqual(ricostruisci(rev, testo), 3)
        rif = {(r.codice_citato, r.sezione): r for r in SgiRiferimento.objects.filter(da_revisione=rev)}
        self.assertTrue(rif[("MOD.093", "§1 Scopo")].risolto)
        self.assertEqual(rif[("MOD.093", "§2 Altro")].occorrenze, 2)
        self.assertEqual(rif[("MOD.093", "§2 Altro")].a_documento, self.mod93)
        self.assertFalse(rif[("MT CN 999", "§1 Scopo")].risolto)
        self.assertIsNone(rif[("MT CN 999", "§1 Scopo")].a_documento)
        # Nuova estrazione: sostituisce, non accumula.
        self.assertEqual(ricostruisci(rev, "solo MT CN 06"), 1)
        self.assertEqual(list(SgiRiferimento.objects.filter(da_revisione=rev).values_list("codice_citato", flat=True)),
                         ["MT CN 06"])

    def test_errore_annulla_la_sostituzione(self):
        rev = _rev("MT CN 78").document.revisions.get()
        ricostruisci(rev, "vedi MOD.093")
        with mock.patch.object(SgiRiferimento.objects, "bulk_create", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                ricostruisci(rev, "vedi MT CN 06")
        self.assertEqual(list(SgiRiferimento.objects.filter(da_revisione=rev).values_list("codice_citato", flat=True)),
                         ["MOD.093"])

    def test_comando_report_e_dry_run(self):
        rev = _rev("MT CN 79").document.revisions.get()
        SgiTestoEstratto.objects.create(revision=rev, file_hash="h", formato="pdf", metodo="t",
                                        testo="vedi MOD.093, MT CN 999 e ISO 9001")
        out = io.StringIO()
        call_command("sgi_riferimenti", "--dry-run", stdout=out)
        self.assertIn('"riferimenti": 2', out.getvalue())
        self.assertIn('"norme_esterne_occorrenze": 1', out.getvalue())
        self.assertIn("MT CN 999", out.getvalue())
        self.assertFalse(SgiRiferimento.objects.exists())
        call_command("sgi_riferimenti", stdout=io.StringIO())
        self.assertEqual(SgiRiferimento.objects.filter(da_revisione=rev).count(), 2)


class CollegaProcessiTests(TestCase):
    def setUp(self):
        from sistema_gestione.models import Processo

        self.doc = _rev("MT CN 06").document
        _rev("MOD.093")
        self.testo_procedure = "Procedura MT CN 06, modulo MOD. 093, vecchio MT CN 999."
        self.processo = Processo.objects.create(codice="P-SINT-01", nome="Processo sintetico",
                                                procedure=self.testo_procedure, fonte_documentale="MT CN 06 Rev.3")

    def test_dry_run_non_scrive(self):
        out = io.StringIO()
        call_command("sgi_collega_processi", "--dry-run", stdout=out)
        self.assertIn("da creare: 2", out.getvalue())
        self.assertIn("MT CN 999", out.getvalue())
        self.assertFalse(SgiDocumentoProcesso.objects.exists())

    def test_apply_crea_proposte_e_non_tocca_il_processo(self):
        call_command("sgi_collega_processi", "--apply", stdout=io.StringIO())
        link = SgiDocumentoProcesso.objects.get(documento=self.doc)
        self.assertFalse(link.confermato)
        self.assertEqual(link.origine, "processo_testo")
        self.assertEqual(SgiDocumentoProcesso.objects.count(), 2)
        self.processo.refresh_from_db()
        self.assertEqual(self.processo.procedure, self.testo_procedure)
        self.assertEqual(self.processo.fonte_documentale, "MT CN 06 Rev.3")
        # Idempotente: un collegamento confermato resta confermato.
        SgiDocumentoProcesso.objects.filter(documento=self.doc).update(confermato=True)
        call_command("sgi_collega_processi", "--apply", stdout=io.StringIO())
        self.assertEqual(SgiDocumentoProcesso.objects.count(), 2)
        self.assertTrue(SgiDocumentoProcesso.objects.get(documento=self.doc).confermato)


class CatenaEstrazioneTests(TestCase):
    def test_nuova_estrazione_ricostruisce_i_riferimenti(self):
        import tempfile
        from pathlib import Path

        from procedure_refresh import sgi_testo

        _rev("MOD.093")
        rev = _rev("MT CN 80")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "MT CN 80.pdf"
            path.write_bytes(b"%PDF-1.4 sintetico")
            rev.source_path = str(path)
            rev.save(update_fields=["source_path"])
            finto = sgi_testo.EstrazioneResult(testo="vedi MOD.093 e MT CN 999", formato="pdf", metodo="t")
            with mock.patch.object(sgi_testo, "estrai", return_value=finto):
                self.assertEqual(sgi_testo.persisti_estrazione(rev, forza=True), "estratto")
        self.assertEqual(sorted(SgiRiferimento.objects.filter(da_revisione=rev).values_list("codice_citato", "risolto")),
                         [("MOD.093", True), ("MT CN 999", False)])


class FamigliaTests(TestCase):
    def setUp(self):
        self.f5 = _rev("MT CN 777_5").document
        self.f10 = _rev("MT CN 777_10").document
        _rev("MOD.093")

    def test_codice_di_famiglia_risolto_con_i_documenti_x_n(self):
        cat = Catalogo()
        esito = cat.dettaglio("MT CN 777")
        self.assertTrue(esito.risolto)
        self.assertEqual(esito.tipo, "famiglia")
        self.assertIsNone(esito.documento)
        self.assertEqual({d.pk for d in esito.famiglia}, {self.f5.pk, self.f10.pk})
        self.assertEqual(cat.dettaglio("MT 777").tipo, "famiglia")  # anche abbreviato senza CN
        self.assertIsNone(cat.risolvi("MT CN 777"))  # nessun documento singolo
        # Non è famiglia: «MT CN 77» non ha documenti «MT CN 77_n» (MT CN 777_5 non conta).
        self.assertFalse(cat.dettaglio("MT CN 77").risolto)
        # Un documento proprio vince sulla famiglia.
        proprio = _rev("MT CN 777").document
        self.assertEqual(Catalogo().dettaglio("MT CN 777").documento, proprio)

    def test_ricostruisci_e_report(self):
        rev = _rev("MT CN 81")
        ricostruisci(rev, "vedi MT CN 777 e MOD.093 e MT CN 999")
        rif = {r.codice_citato: r for r in SgiRiferimento.objects.filter(da_revisione=rev)}
        self.assertTrue(rif["MT CN 777"].risolto)
        self.assertEqual(rif["MT CN 777"].tipo_risoluzione, "famiglia")
        self.assertIsNone(rif["MT CN 777"].a_documento)
        self.assertEqual(set(rif["MT CN 777"].documenti_famiglia()), {self.f5, self.f10})
        self.assertEqual(rif["MOD.093"].tipo_risoluzione, "esatto")
        self.assertEqual(rif["MT CN 999"].tipo_risoluzione, "")
        SgiTestoEstratto.objects.create(revision=rev, file_hash="h", formato="pdf", metodo="t",
                                        testo="vedi MT CN 777 e MOD.093 e MT CN 999")
        out = io.StringIO()
        call_command("sgi_riferimenti", "--dry-run", stdout=out)
        report = __import__("json").loads(out.getvalue())
        self.assertEqual(report["risolti"], 2)
        self.assertEqual(report["quota_risolti"], round(2 / 3, 3))
        self.assertEqual(report["risolti_per_tipo"]["famiglia"], 1)
        self.assertEqual(report["famiglie_citate"][0]["codice"], "MT CN 777")
        self.assertEqual([c["codice"] for c in report["top15_codici_inesistenti"]], ["MT CN 999"])


class ImportUtenteEFileElencatiTests(TestCase):
    def test_utente_di_processo_e_avviso_se_cambia_il_numero_di_file(self):
        import json
        import tempfile
        from pathlib import Path

        from core.models import SiteConfig

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for nome in ("MT CN 901 Rev.1_Procedura sintetica.pdf", "MOD.991 - Modulo sintetico Rev.0.pdf"):
                (root / nome).write_bytes(b"%PDF-1.4 sintetico")
            out = io.StringIO()
            call_command("import_sgi_da_share", "--root", str(root), "--apply", "--json", stdout=out)
            s = json.loads(out.getvalue())["summary"]
            self.assertTrue(s["utente_processo"])
            self.assertEqual(s["file_elencati"], 2)
            self.assertEqual(s["avviso_file_elencati"], "")
            registrata = json.loads(SiteConfig.get("pr_sgi_scan_ultima", ""))
            self.assertEqual(registrata["file_elencati"], 2)

            (root / "MT CN 902 Rev.0_Altra procedura.pdf").write_bytes(b"%PDF-1.4 sintetico")
            out = io.StringIO()
            call_command("import_sgi_da_share", "--root", str(root), stdout=out)  # dry-run, testo
            self.assertIn("ATTENZIONE: File elencati sulla share: 3", out.getvalue())
            self.assertIn("erano 2", out.getvalue())
            # Il dry-run non registra nulla e non cambia cosa si importerebbe.
            self.assertEqual(json.loads(SiteConfig.get("pr_sgi_scan_ultima", ""))["file_elencati"], 2)
            self.assertIn("MT CN 902", out.getvalue())
