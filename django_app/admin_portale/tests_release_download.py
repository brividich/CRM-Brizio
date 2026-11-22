"""Audit S3: il download del pacchetto accetta solo zip dentro le cartelle dei pacchetti."""
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from admin_portale.views import release


class PacchettoAmmessoTests(SimpleTestCase):
    def setUp(self):
        self.radice = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.radice, ignore_errors=True)
        self.pacchetti = self.radice / "packages"
        self.altrove = self.radice / "altrove"
        self.pacchetti.mkdir()
        self.altrove.mkdir()
        patcher = patch.object(release, "_cartelle_pacchetti", return_value=(self.pacchetti, self.radice / "releases"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _zip(self, cartella: Path, nome: str = "portale-novicrom-1.0.zip") -> Path:
        f = cartella / nome
        f.write_bytes(b"PK\x03\x04")
        return f

    def test_zip_nella_cartella_dei_pacchetti_ammesso(self):
        f = self._zip(self.pacchetti)
        self.assertEqual(release._pacchetto_ammesso(str(f)), f.resolve())

    def test_zip_con_lo_stesso_nome_in_altra_cartella_rifiutato(self):
        f = self._zip(self.altrove)
        self.assertIsNone(release._pacchetto_ammesso(str(f)))

    def test_risalita_di_cartella_rifiutata(self):
        self._zip(self.altrove)
        grezzo = str(self.pacchetti / ".." / "altrove" / "portale-novicrom-1.0.zip")
        self.assertIsNone(release._pacchetto_ammesso(grezzo))

    def test_nome_o_estensione_diversi_rifiutati(self):
        self.assertIsNone(release._pacchetto_ammesso(str(self._zip(self.pacchetti, "altro.zip"))))
        self.assertIsNone(release._pacchetto_ammesso(str(self._zip(self.pacchetti, "portale-novicrom-1.0.txt"))))

    def test_file_inesistente_rifiutato(self):
        self.assertIsNone(release._pacchetto_ammesso(str(self.pacchetti / "portale-novicrom-x.zip")))
        self.assertIsNone(release._pacchetto_ammesso(""))
