"""Sigillo mensile dell'audit (core.audit_sigilli) ed export su SharePoint (dati sintetici)."""
from __future__ import annotations

import gzip
import json
from datetime import date, datetime
from io import StringIO
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from core import audit_sigilli as sig
from core import sharepoint_upload as sp
from core.models import AuditLog, AuditSigillo, SiteConfig

OGGI = date(2026, 10, 18)


def _riga(quando: datetime, azione="login", **extra):
    r = AuditLog.objects.create(azione=azione, modulo="core", utente_display="Utente sintetico",
                                dettaglio=extra.pop("dettaglio", {"esito": "ok"}), **extra)
    AuditLog.objects.filter(pk=r.pk).update(created_at=timezone.make_aware(quando))
    return r


class SigilliTests(TestCase):
    def setUp(self):
        self.ago1 = _riga(datetime(2026, 8, 3, 9, 0))
        self.ago2 = _riga(datetime(2026, 8, 20, 17, 30), azione="approvazione")
        self.set1 = _riga(datetime(2026, 9, 10, 8, 0))
        self.tecnica = _riga(datetime(2026, 9, 11, 8, 0), azione="auto_update", dettaglio={"model": "x", "modifiche": {"a": 1}})
        self.corrente = _riga(datetime(2026, 10, 2, 8, 0))

    def _sigilla(self):
        with patch.object(sig, "mese_corrente", return_value="2026-10"):
            return sig.sigilla_mancanti(OGGI)

    def test_sigilla_i_mesi_conclusi_in_catena(self):
        creati = self._sigilla()
        self.assertEqual([s.mese for s in creati], ["2026-08", "2026-09"])
        ago, sett = creati
        self.assertEqual(ago.hash_precedente, sig.GENESI)
        self.assertEqual(sett.hash_precedente, ago.hash_sigillo)
        self.assertEqual(ago.righe, 2)
        self.assertEqual(sett.righe, 1)  # la riga auto_update non è coperta
        self.assertFalse(AuditSigillo.objects.filter(mese="2026-10").exists())  # mese in corso
        self.assertEqual(self._sigilla(), [])  # idempotente

    def test_verifica_ok(self):
        self._sigilla()
        esiti = sig.verifica()
        self.assertEqual([e["stato"] for e in esiti], ["ok", "ok"])
        self.assertTrue(all(AuditSigillo.objects.values_list("verifica_ok", flat=True)))

    def test_riga_modificata_rompe_il_mese(self):
        self._sigilla()
        AuditLog.objects.filter(pk=self.ago2.pk).update(dettaglio={"esito": "ko"})
        esiti = {e["mese"]: e for e in sig.verifica()}
        self.assertEqual(esiti["2026-08"]["stato"], "rotto")
        self.assertEqual(esiti["2026-09"]["stato"], "ok")

    def test_riga_cancellata_o_aggiunta_rompe(self):
        self._sigilla()
        AuditLog.objects.filter(pk=self.set1.pk).delete()
        self.assertEqual({e["mese"]: e["stato"] for e in sig.verifica()}["2026-09"], "rotto")
        _riga(datetime(2026, 9, 12, 8, 0))
        self.assertEqual({e["mese"]: e["stato"] for e in sig.verifica()}["2026-09"], "rotto")

    def test_sigillo_alterato_rompe_la_catena(self):
        self._sigilla()
        AuditSigillo.objects.filter(mese="2026-08").update(righe=99)
        esiti = {e["mese"]: e for e in sig.verifica()}
        self.assertEqual(esiti["2026-08"]["stato"], "rotto")
        AuditSigillo.objects.filter(mese="2026-08").update(righe=2, hash_sigillo="f" * 64)
        esiti = {e["mese"]: e for e in sig.verifica()}
        self.assertEqual(esiti["2026-09"]["stato"], "rotto")  # il successivo non si aggancia più
        self.assertIn("catena", esiti["2026-09"]["motivo"])

    def test_righe_tecniche_archiviate_non_rompono(self):
        self._sigilla()
        AuditLog.objects.filter(pk=self.tecnica.pk).delete()  # come fa audit_archive per politica
        self.assertEqual([e["stato"] for e in sig.verifica()], ["ok", "ok"])

    def test_comando_verifica_esce_con_errore_se_rotta(self):
        self._sigilla()
        call_command("audit_sigilli", "--verifica", stdout=StringIO())
        AuditLog.objects.filter(pk=self.ago1.pk).update(utente_display="Altro")
        with self.assertRaises(CommandError):
            call_command("audit_sigilli", "--verifica", stdout=StringIO())

    def test_file_export_ricalcolabile(self):
        ago = self._sigilla()[0]
        righe_gz, meta_json = sig.file_export(ago)
        linee = gzip.decompress(righe_gz).decode("utf-8").splitlines()
        self.assertEqual(len(linee), 2)
        meta = json.loads(meta_json)
        self.assertEqual(meta["hash_sigillo"], ago.hash_sigillo)
        # Chiunque può ricalcolare l'hash dalle righe del file.
        import hashlib

        h = hashlib.sha256()
        for linea in linee:
            h.update(hashlib.sha256(linea.encode("utf-8")).hexdigest().encode("ascii") + b"\n")
        self.assertEqual(h.hexdigest(), meta["hash_righe"])

    def test_export_senza_cartella_resta_da_fare(self):
        self._sigilla()
        esito = sig.esporta_mancanti()
        self.assertFalse(esito["configurato"])
        self.assertTrue(all(not s.export_ok and "non configurata" in s.export_errore for s in AuditSigillo.objects.all()))

    def test_export_su_sharepoint_in_ordine(self):
        self._sigilla()
        SiteConfig.set("audit_export_sp_drive_id", "b!drive-sintetico", "")
        SiteConfig.set("audit_export_sp_cartella", "Audit/Portale", "")
        with patch.object(sp, "carica", return_value="https://sharepoint.example/Audit/x") as carica:
            esito = sig.esporta_mancanti()
        self.assertEqual(esito["esportati"], 2)
        nomi = [c.args[0] for c in carica.call_args_list]
        self.assertEqual(nomi, ["audit-2026-08.jsonl.gz", "audit-2026-08.sigillo.json",
                                "audit-2026-09.jsonl.gz", "audit-2026-09.sigillo.json"])
        self.assertTrue(all(AuditSigillo.objects.values_list("export_ok", flat=True)))

    def test_export_si_ferma_al_primo_errore(self):
        self._sigilla()
        SiteConfig.set("audit_export_sp_drive_id", "b!drive-sintetico", "")
        SiteConfig.set("audit_export_sp_cartella", "Audit", "")
        with patch.object(sp, "carica", side_effect=sp.SharePointUploadError("403")):
            esito = sig.esporta_mancanti()
        self.assertEqual(esito["errori"], 1)
        self.assertEqual(AuditSigillo.objects.get(mese="2026-08").export_errore, "403")
        self.assertEqual(AuditSigillo.objects.get(mese="2026-09").export_errore, "")

    def test_ciclo_mensile_avvisa_se_rotta(self):
        self._sigilla()
        AuditLog.objects.filter(pk=self.ago1.pk).update(modulo="manomesso")
        with patch("django.core.mail.mail_admins") as mail, patch.object(sig, "mese_corrente", return_value="2026-10"):
            esito = sig.ciclo_mensile()
        self.assertEqual(esito["rotti"], 1)
        mail.assert_called_once()


class SharePointUploadTests(TestCase):
    def test_nome_file_non_valido(self):
        with self.assertRaises(sp.SharePointUploadError):
            sp.carica("../x.json", b"{}", drive_id="d", cartella="c")

    def test_file_esistente_non_sovrascritto(self):
        class R:
            status_code = 409

            def json(self):
                return {"error": {"code": "nameAlreadyExists"}}

        with patch.object(sp, "_token", return_value="t"), patch("requests.put", return_value=R()) as put:
            with self.assertRaises(sp.SharePointUploadError) as ctx:
                sp.carica("audit-2026-08.sigillo.json", b"{}", drive_id="b!d", cartella="Audit")
        self.assertIn("conflictBehavior=fail", put.call_args.args[0])
        self.assertIn("non sovrascritto", str(ctx.exception))
