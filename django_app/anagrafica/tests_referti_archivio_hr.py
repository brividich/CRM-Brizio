"""Lettura dei referti dell'archivio HR TOOLS e registrazione delle visite (dati sintetici)."""
from __future__ import annotations

import shutil
import tempfile
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from .models import DipendenteAnagraficaCivile, DocumentoDipendente, TipoVisitaMedica, VisitaMedica
from .models_sorveglianza import AliasEsitoIdoneita, RefertoIntakeRiga
from .tests import _ensure_anagrafica_table
from .tests_exports_persone import _insert_dipendente
from .tests_referti_intake import CERTIFICATO

PDF = b"%PDF-1.4 referto sintetico"


class LeggiRefertiArchivioTests(TestCase):
    def setUp(self):
        self.private = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.private, ignore_errors=True)
        override = override_settings(ANAGRAFICA_PRIVATE_ROOT=str(self.private))
        override.enable()
        self.addCleanup(override.disable)

        _ensure_anagrafica_table()
        self.legacy_id = _insert_dipendente(7201, "Giuseppe", "Verdi")
        self.civile = DipendenteAnagraficaCivile.objects.create(
            legacy_anagrafica_id=self.legacy_id, data_nascita=date(1975, 4, 11),
        )
        TipoVisitaMedica.objects.create(nome="Visita Medica", durata_mesi=12)
        self.oculistica = TipoVisitaMedica.objects.create(nome="Visita Oculistica", durata_mesi=24)
        AliasEsitoIdoneita.objects.create(
            testo="IDONEO MANSIONE SPECIFICA", esito=VisitaMedica.Esito.IDONEO_MANSIONE
        )

        self.doc = DocumentoDipendente(
            legacy_anagrafica_id=self.legacy_id,
            tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
            nome_originale="idoneita_2024.pdf",
            oggetto_riferimento_tipo="archivio.hrtools",
        )
        self.doc.file.save("idoneita_2024.pdf", ContentFile(PDF), save=True)

        self.testo = CERTIFICATO
        for bersaglio, valore in (
            ("anagrafica.services.referti_ocr.disponibile", lambda: True),
            ("anagrafica.services.referti_ocr.conta_pagine", lambda contenuto: 1),
            ("anagrafica.services.referti_ocr.testo_pagina", lambda c, p=0, config=None: self.testo),
        ):
            patcher = patch(bersaglio, valore)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _run(self, *args) -> str:
        out = StringIO()
        call_command("leggi_referti_archivio", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_non_scrive(self):
        out = self._run()
        self.assertIn("REGISTRA", out)
        self.assertIn("verrebbero create: 2", out)
        self.assertFalse(VisitaMedica.objects.exists())
        self.assertFalse(RefertoIntakeRiga.objects.exists())

    def test_apply_registra_visite_sul_documento_esistente_e_non_rilegge(self):
        self._run("--apply")
        visite = VisitaMedica.objects.filter(legacy_anagrafica_id=self.legacy_id)
        self.assertEqual(visite.count(), 2)
        self.assertTrue(all(v.referto_documento_id == self.doc.pk for v in visite))
        self.assertEqual(visite.first().data_svolgimento, date(2024, 3, 15))
        self.assertEqual(DocumentoDipendente.objects.count(), 1)  # nessuna copia del file
        riga = RefertoIntakeRiga.objects.get()
        self.assertEqual(riga.esito, RefertoIntakeRiga.ESITO_OK)
        self.assertEqual(riga.documento_id, self.doc.pk)

        out = self._run("--apply")
        self.assertIn("GIA_LETTO", out)
        self.assertEqual(VisitaMedica.objects.count(), 2)
        self.assertEqual(RefertoIntakeRiga.objects.count(), 1)

    def test_data_nascita_diversa_va_in_revisione(self):
        self.civile.data_nascita = date(1980, 1, 1)
        self.civile.save()
        self._run("--apply")
        self.assertFalse(VisitaMedica.objects.exists())
        riga = RefertoIntakeRiga.objects.get()
        self.assertEqual(riga.esito, RefertoIntakeRiga.ESITO_DA_RIVEDERE)
        self.assertIn("Data di nascita", riga.messaggio)
        self.assertEqual(riga.legacy_anagrafica_id_proposto, self.legacy_id)

    def test_esame_non_a_catalogo_va_in_revisione_e_compare_nel_riepilogo(self):
        self.oculistica.delete()
        out = self._run()
        self.assertIn("Esami NON a catalogo", out)
        self.assertIn("Visita Oculistica", out)
        self.assertIn("REVISIONE", out)

    def test_pagina_non_certificato_ignorata(self):
        self.testo = "Richiesta di visita medica straordinaria"
        self._run("--apply")
        self.assertFalse(RefertoIntakeRiga.objects.exists())
        self.assertFalse(VisitaMedica.objects.exists())

    def test_cartella_solo_in_dry_run(self):
        with self.assertRaises(CommandError):
            self._run("--apply", "--cartella", str(self.private))
