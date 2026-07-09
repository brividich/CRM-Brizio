"""Test del comando import_suggestion_corner_legacy (sessione 8)."""
from __future__ import annotations

import json
import os
import tempfile

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from anagrafica.models import Reparto
from suggestion_corner.models import SuggestionCorner

User = get_user_model()


class ImportLegacyTest(TestCase):
    def setUp(self):
        self.torni = Reparto.objects.create(nome="TORNI")
        self.cnc = Reparto.objects.create(nome="CNC")
        self.mario = User.objects.create_user(username="mario", email="mario@x.it")

    def _write(self, records):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(records, fh)
        self.addCleanup(lambda: os.remove(path))
        return path

    def _write_map(self, mapping):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(mapping, fh)
        self.addCleanup(lambda: os.remove(path))
        return path

    def _record(self, **kw):
        base = {
            "sharepoint_id": 1,
            "data_segnalazione": "2024-03-15",
            "reparto_provenienza": "torni",  # case-insensitive
            "reparto_destinazione": "CNC",
            "opportunity": "Migliorare l'illuminazione.",
            "autore_email": "mario@x.it",
            "incaricato_email": "mario@x.it",
            "esito_check": "RINVIATO",
            "allegati": [r"\\novisrv\Area Qualita\SMS\2024"],
            "stato": "CHIUSA",
        }
        base.update(kw)
        return base

    def test_dry_run_non_scrive(self):
        path = self._write([self._record()])
        call_command("import_suggestion_corner_legacy", file=path)  # no --apply
        self.assertEqual(SuggestionCorner.objects.count(), 0)

    def test_apply_crea_record(self):
        path = self._write([self._record()])
        call_command("import_suggestion_corner_legacy", file=path, apply=True)
        self.assertEqual(SuggestionCorner.objects.count(), 1)
        seg = SuggestionCorner.objects.get()
        self.assertEqual(seg.legacy_sharepoint_id, 1)
        self.assertFalse(seg.da_portale)
        self.assertEqual(seg.stato, "CHIUSA")  # impostato via .update()
        self.assertEqual(seg.reparto_provenienza, self.torni)
        self.assertEqual(seg.reparto_destinazione, self.cnc)
        self.assertEqual(seg.incaricato, self.mario)
        self.assertEqual(seg.esito_check, "RINVIATO")
        self.assertEqual(seg.allegati.count(), 1)
        self.assertIn("novisrv", seg.allegati.get().link_esterno)
        self.assertTrue(seg.storico.filter(valore_nuovo="Importato da SharePoint").exists())

    def test_idempotente(self):
        path = self._write([self._record()])
        call_command("import_suggestion_corner_legacy", file=path, apply=True)
        call_command("import_suggestion_corner_legacy", file=path, apply=True)  # secondo run
        self.assertEqual(SuggestionCorner.objects.count(), 1)  # non duplica

    def test_reparto_mancante_salta_record(self):
        path = self._write([self._record(reparto_provenienza="INESISTENTE")])
        call_command("import_suggestion_corner_legacy", file=path, apply=True)
        self.assertEqual(SuggestionCorner.objects.count(), 0)

    def test_reparto_map_rimappa_provenienza(self):
        # 'LOG' del CSV va rimappato sul catalogo 'CNC'; 'Generico' → ignorato (vuoto).
        path = self._write([self._record(
            reparto_provenienza="LOG", reparto_destinazione="Generico")])
        mp = self._write_map({"LOG": "CNC", "Generico": ""})
        call_command("import_suggestion_corner_legacy", file=path, apply=True, reparto_map=mp)
        seg = SuggestionCorner.objects.get()
        self.assertEqual(seg.reparto_provenienza, self.cnc)
        self.assertIsNone(seg.reparto_destinazione)  # mappato a vuoto

    def test_anonima_no_created_by(self):
        path = self._write([self._record(anonima=True)])
        call_command("import_suggestion_corner_legacy", file=path, apply=True)
        seg = SuggestionCorner.objects.get()
        self.assertTrue(seg.anonima)
        self.assertIsNone(seg.created_by)
