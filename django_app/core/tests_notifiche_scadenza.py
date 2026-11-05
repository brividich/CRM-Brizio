"""Promemoria di scadenza: scaletta e archiviazione di quelli finiti sull'account sbagliato."""
from __future__ import annotations

from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core.models import Notifica
from core.notifiche import giorno_di_promemoria


class ScalettaTests(SimpleTestCase):
    def test_prima_della_scadenza(self):
        giorni = [g for g in range(0, 31) if giorno_di_promemoria(g, 30)]
        self.assertEqual(giorni, [0, 1, 7, 14, 30])

    def test_dopo_la_scadenza(self):
        giorni = [g for g in range(-16, 0) if giorno_di_promemoria(g, 30)]
        self.assertEqual(giorni, [-15, -8, -1])


class ArchiviazioneTests(TestCase):
    def _crea(self, legacy_user_id, tipo="visita_scadenza", giorni_fa=3):
        n = Notifica.objects.create(legacy_user_id=legacy_user_id, tipo=tipo, messaggio="Visita medica scaduta: sintetica.")
        Notifica.objects.filter(pk=n.pk).update(created_at=timezone.now() - timedelta(days=giorni_fa))
        return n

    def _lancia(self, *argomenti):
        out = StringIO()
        righe = SimpleNamespace(values_list=lambda *a: [(1, 1), (2, 50)])
        with patch("core.legacy_models.AnagraficaDipendente.objects", righe):
            oggi = timezone.localdate().isoformat()
            call_command("archivia_notifiche_scadenza_errate", f"--fino-al={oggi}", *argomenti, stdout=out)
        return out.getvalue()

    def test_prova_non_tocca_nulla(self):
        n = self._crea(2)
        testo = self._lancia()
        self.assertIn("Da archiviare: 1", testo)
        n.refresh_from_db()
        self.assertFalse(n.archiviata)

    def test_archivia_solo_le_errate_e_non_cancella(self):
        giusta = self._crea(1)              # numero di anagrafica = utente della stessa persona
        sbagliata = self._crea(2)           # l'utente vero è 50
        senza = self._crea(99)              # non è di nessuno
        altro_tipo = self._crea(2, tipo="capa")
        dopo = self._crea(2, giorni_fa=-2)  # creata dopo la data indicata
        self._lancia("--apply")
        for n, atteso in ((giusta, False), (sbagliata, True), (senza, True), (altro_tipo, False), (dopo, False)):
            n.refresh_from_db()
            self.assertEqual(n.archiviata, atteso, n.pk)
        self.assertEqual(Notifica.objects.count(), 5)
        sbagliata.refresh_from_db()
        self.assertEqual(sbagliata.archiviata_motivo, "admin")
