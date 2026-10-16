"""La configurazione del modulo anomalie sopravvive ai deploy.

Ogni deploy di produzione è una cartella nuova ``releases/<tag>``: il vecchio file
``config/anomalie_liste.json`` restava nella release precedente e capi reparto/commessa,
liste, destinatari e logo tornavano ai default. Ora la fonte è il DB (SiteConfig).
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings

from anomalie import views as anomalie_views
from core.models import SiteConfig

DATI = {
    "menu_logo": "/media/anomalie_logo/menu_logo.png",
    "conferma_aggiornamenti": ["qualita@example.test"],
    "derived_sources": {
        "capi_reparto": {"ruoli": [], "extra": [], "esclusi": ["MARIO ROSSI"]},
        "capi_commessa": {"ruoli": [7], "extra": [], "esclusi": []},
    },
}


class ConfigPersistenteTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        p = override_settings(PRIVATE_ATTACHMENTS_ROOT=str(self.root / "media_private"))
        p.enable()
        self.addCleanup(p.disable)

    def _release(self, tag: str, payload: dict | None, mtime: float | None = None) -> Path:
        rel = self.root / "releases" / tag
        (rel / "config").mkdir(parents=True)
        if payload is not None:
            f = rel / "config" / "anomalie_liste.json"
            f.write_text(json.dumps(payload), encoding="utf-8")
            if mtime:
                os.utime(f, (mtime, mtime))
        return rel

    def test_salvataggio_va_nel_db_e_resta_dopo_il_deploy(self):
        vecchia = self._release("20260101_000000", None)
        with patch.object(anomalie_views, "_repo_root", return_value=vecchia):
            anomalie_views._save_anomalie_menu_logo("/media/anomalie_logo/menu_logo.png")
            anomalie_views._save_anomalie_derived_sources(DATI["derived_sources"])
        self.assertFalse((vecchia / "config" / "anomalie_liste.json").exists())
        # deploy: nuova cartella senza config
        nuova = self._release("20260102_000000", None)
        with patch.object(anomalie_views, "_repo_root", return_value=nuova):
            self.assertEqual(anomalie_views._load_anomalie_menu_logo(), "/media/anomalie_logo/menu_logo.png")
            fonti = anomalie_views._load_anomalie_derived_sources()
        self.assertEqual(fonti["capi_commessa"]["ruoli"], [7])
        self.assertEqual(fonti["capi_reparto"]["esclusi"], ["MARIO ROSSI"])

    def test_primo_avvio_importa_dalla_release_precedente_piu_recente(self):
        ora = time.time()
        self._release("20260101_000000", {"menu_logo": "/vecchio.png"}, mtime=ora - 7200)
        self._release("20260102_000000", DATI, mtime=ora - 60)
        nuova = self._release("20260103_000000", None)
        with patch.object(anomalie_views, "_repo_root", return_value=nuova):
            self.assertEqual(anomalie_views._load_anomalie_menu_logo(), DATI["menu_logo"])
            self.assertIn("qualita@example.test", anomalie_views._load_anomalie_lists()["conferma_aggiornamenti"])
        salvato = json.loads(SiteConfig.get(anomalie_views.ANOMALIE_CONFIG_SITECONFIG_KEY))
        self.assertEqual(salvato["derived_sources"]["capi_commessa"]["ruoli"], [7])

    def test_import_dalla_copia_in_media_private(self):
        copia = self.root / "media_private" / "anomalie_config" / "anomalie_liste.json"
        copia.parent.mkdir(parents=True)
        copia.write_text(json.dumps(DATI), encoding="utf-8")
        nuova = self._release("20260103_000000", None)
        with patch.object(anomalie_views, "_repo_root", return_value=nuova):
            self.assertEqual(anomalie_views._load_anomalie_menu_logo(), DATI["menu_logo"])

    def test_db_vince_sul_file(self):
        SiteConfig.set(anomalie_views.ANOMALIE_CONFIG_SITECONFIG_KEY, json.dumps({"menu_logo": "/db.png"}))
        rel = self._release("20260103_000000", {"menu_logo": "/file.png"})
        with patch.object(anomalie_views, "_repo_root", return_value=rel):
            self.assertEqual(anomalie_views._load_anomalie_menu_logo(), "/db.png")
