from django.test import TestCase

from core.acl_bootstrap_base import upsert_pulsante
from core.legacy_models import Pulsante


class UpsertPulsanteTests(TestCase):
    """Due definizioni con lo stesso URL non devono rubarsi la stessa riga."""

    def _run(self, definitions):
        riservati = {d[1] for d in definitions}
        changed = False
        for modulo, codice, url in definitions:
            _, item_changed = upsert_pulsante(modulo, codice, codice.upper(), url, codici_riservati=riservati)
            changed = changed or item_changed
        return changed

    def test_url_condiviso_crea_due_righe_stabili(self):
        defs = [("timbri", "timbri_home", "/timbri/"), ("timbri", "timbri_copy", "/timbri/")]
        self._run(defs)
        self.assertEqual(
            set(Pulsante.objects.filter(modulo="timbri").values_list("codice", flat=True)),
            {"timbri_home", "timbri_copy"},
        )
        # Secondo e terzo avvio: nessuna modifica.
        self.assertFalse(self._run(defs))
        self.assertFalse(self._run(defs))

    def test_riga_esistente_condivisa_non_viene_rinominata(self):
        Pulsante.objects.create(modulo="timbri", codice="timbri_home", nome_visibile="x", url="/timbri/")
        self._run([("timbri", "timbri_home", "/timbri/"), ("timbri", "timbri_copy", "/timbri/")])
        self.assertTrue(Pulsante.objects.filter(modulo="timbri", codice="timbri_home").exists())
        self.assertTrue(Pulsante.objects.filter(modulo="timbri", codice="timbri_copy").exists())

    def test_url_vuoto_non_aggancia_altre_righe(self):
        Pulsante.objects.create(modulo="assets", codice="maintenance_planning", nome_visibile="x", url="")
        upsert_pulsante("assets", "asset_qr_public", "QR", "", codici_riservati={"maintenance_planning", "asset_qr_public"})
        self.assertEqual(Pulsante.objects.filter(modulo="assets").count(), 2)

    def test_rinomina_codice_via_url_resta_possibile(self):
        vecchio = Pulsante.objects.create(modulo="anagrafica", codice="vecchio", nome_visibile="x", url="/anagrafica/x/")
        pid, changed = upsert_pulsante("anagrafica", "nuovo", "Nuovo", "/anagrafica/x/", codici_riservati={"nuovo"})
        self.assertEqual(pid, vecchio.id)
        self.assertTrue(changed)
        vecchio.refresh_from_db()
        self.assertEqual(vecchio.codice, "nuovo")
