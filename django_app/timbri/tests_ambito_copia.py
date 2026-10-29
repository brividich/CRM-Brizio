"""Copia e download di timbri/firme/sigle: ambito «propri / team / tutti» e registro.

Motore dei permessi vero (matrice dei ruoli), view chiamate con RequestFactory.
Organigramma sintetico: capo squadra <- operaio; «altro» fuori dal team.
"""
from __future__ import annotations

import io
import shutil
import tempfile
from unittest.mock import patch

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings

from core.models import AccessGroup, AuditLog, RuoloPermessoModulo
from core.permessi.cache import invalida_permessi
from core.tests_permessi_moduli import ModuliBase

from . import views
from .models import OperatoreTimbri, RegistroTimbro, RegistroTimbroImmagine


def _png(name="t.png"):
    buffer = io.BytesIO()
    Image.new("RGBA", (4, 4), (0, 0, 0, 255)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class AmbitoCopiaDownloadTests(ModuliBase):
    def setUp(self):
        super().setUp()
        self.private_root = tempfile.mkdtemp(prefix="timbri-ambito-")
        self._override = override_settings(TIMBRI_PRIVATE_ROOT=self.private_root)
        self._override.enable()
        self.ruolo = AccessGroup.objects.create(code="test-timbri-copia", label="Test timbri copia", priority=900)
        RuoloPermessoModulo.objects.create(ruolo=self.ruolo, modulo="timbri", azione="vedere", ambito="tutti")

        self.capo, self.capo_l = self.persona("Capo", ruoli=("test-timbri-copia",))
        self.op, self.op_l = self.persona("Operaio")
        self.altro, self.altro_l = self.persona("Altro")
        self.nell_organigramma(self.capo_l, self.r_capo)
        self.nell_organigramma(self.op_l, self.r_op)
        with connection.cursor() as c:
            c.execute(
                "INSERT INTO anagrafica_dipendenti (id, nome, utente_id) VALUES (%s, %s, %s)",
                [7000 + self.altro_l.id, self.altro_l.nome, self.altro_l.id],
            )
        self.img_capo = self.immagine(self.capo_l, "CNO C1")
        self.img_op = self.immagine(self.op_l, "CNO O1")
        self.img_altro = self.immagine(self.altro_l, "CNO A1")

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self.private_root, ignore_errors=True)
        super().tearDown()

    def immagine(self, legacy, codice):
        operatore = OperatoreTimbri.objects.create(nome=legacy.nome, legacy_anagrafica_id=7000 + legacy.id)
        registro = RegistroTimbro.objects.create(operatore=operatore, codice_timbro=codice)
        img = RegistroTimbroImmagine(registro=registro, variante=RegistroTimbroImmagine.VARIANTE_FIRMA, image=_png())
        img.save()
        return img

    def concedi(self, azione, ambito):
        RuoloPermessoModulo.objects.update_or_create(
            ruolo=self.ruolo, modulo="timbri", azione=azione, defaults={"ambito": ambito, "consentito": True},
        )
        invalida_permessi()

    def get(self, img, flag):
        request = self.req(self.capo, self.capo_l, path="/timbri/immagine/", data={flag: "1"})
        return views.serve_timbri_image(request, img.id).status_code

    def test_senza_cella_niente_copia_ne_download(self):
        self.assertEqual(self.get(self.img_capo, "copy"), 403)
        self.assertEqual(self.get(self.img_capo, "download"), 403)

    def test_propri_solo_i_suoi(self):
        self.concedi("copiare", "propri")
        self.assertEqual(self.get(self.img_capo, "copy"), 200)
        self.assertEqual(self.get(self.img_op, "copy"), 403)
        self.assertEqual(self.get(self.img_altro, "copy"), 403)
        # Copiare non concede scaricare.
        self.assertEqual(self.get(self.img_capo, "download"), 403)

    def test_team_anche_quelli_del_team(self):
        self.concedi("scaricare", "team")
        self.assertEqual(self.get(self.img_capo, "download"), 200)
        self.assertEqual(self.get(self.img_op, "download"), 200)
        self.assertEqual(self.get(self.img_altro, "download"), 403)

    def test_tutti(self):
        self.concedi("copiare", "tutti")
        for img in (self.img_capo, self.img_op, self.img_altro):
            self.assertEqual(self.get(img, "copy"), 200)

    def test_registro_traccia_titolare_ambito_e_negati(self):
        self.concedi("scaricare", "propri")
        self.get(self.img_capo, "download")
        self.get(self.img_altro, "download")
        ok = AuditLog.objects.filter(azione="timbri_image_download").latest("id")
        self.assertEqual(ok.dettaglio["codice_timbro"], "CNO C1")
        self.assertEqual(ok.dettaglio["ambito"], "propri")
        self.assertEqual(ok.oggetto_id, str(self.img_capo.id))
        negato = AuditLog.objects.filter(azione="timbri_image_denied").latest("id")
        self.assertEqual(negato.dettaglio["motivo"], "fuori_ambito")
        self.assertEqual(negato.dettaglio["codice_timbro"], "CNO A1")

        request = self.req(self.capo, self.capo_l, data={"tab": "registro"})
        righe = views._registro_copie_context(request)["registro_righe"]
        esiti = [(r["esito"], r["codice"]) for r in righe]
        self.assertIn(("Download", "CNO C1"), esiti)
        self.assertIn(("Download negato", "CNO A1"), esiti)

    def test_anteprima_elenco_decide_per_persona(self):
        import json

        self.concedi("copiare", "team")
        def anteprima(legacy):
            request = self.req(self.capo, self.capo_l)
            # «Vedere» passa dai permessi di pagina sincronizzati: qui conta solo copia/download.
            with patch("timbri.views._can_view_timbri", return_value=True):
                return json.loads(views.operatore_preview(request, 7000 + legacy.id).content)

        self.assertTrue(anteprima(self.op_l)["can_copy_timbri"])
        self.assertFalse(anteprima(self.altro_l)["can_copy_timbri"])
        self.assertFalse(anteprima(self.op_l)["can_download_timbri"])


class ImpostazioniAmbitiTests(ModuliBase):
    def setUp(self):
        super().setUp()
        self.ruolo = AccessGroup.objects.create(code="test-timbri-imp", label="Test timbri imp", priority=300)
        self.admin, self.admin_l = self.persona("Admin", ruoli=("ruolo-amministratore",))
        self.qualita, self.qualita_l = self.persona("Qualità", ruoli=("ruolo-qualita",))

    def post(self, user, legacy, data):
        return self.req(user, legacy, method="post", data={"action": "save_ambiti", **data})

    def test_amministratore_salva_le_celle_e_lascia_traccia(self):
        chiave = f"ambito__{self.ruolo.id}__copiare"
        views._salva_ambiti_ruoli(self.post(self.admin, self.admin_l, {chiave: "team"}))
        cella = RuoloPermessoModulo.objects.get(ruolo=self.ruolo, modulo="timbri", azione="copiare")
        self.assertEqual((cella.consentito, cella.ambito), (True, "team"))
        log = AuditLog.objects.filter(azione="timbri_permessi_ambito").latest("id")
        self.assertEqual(log.dettaglio["modifiche"][0]["dopo"], "team")

        views._salva_ambiti_ruoli(self.post(self.admin, self.admin_l, {chiave: "no"}))
        cella.refresh_from_db()
        self.assertFalse(cella.consentito)
        views._salva_ambiti_ruoli(self.post(self.admin, self.admin_l, {chiave: ""}))
        self.assertFalse(RuoloPermessoModulo.objects.filter(ruolo=self.ruolo, azione="copiare").exists())

    def test_valore_sconosciuto_ignorato(self):
        chiave = f"ambito__{self.ruolo.id}__scaricare"
        views._salva_ambiti_ruoli(self.post(self.admin, self.admin_l, {chiave: "chiunque"}))
        self.assertFalse(RuoloPermessoModulo.objects.filter(ruolo=self.ruolo, azione="scaricare").exists())

    def test_chi_gestisce_le_impostazioni_ma_non_e_amministratore_non_cambia_i_ruoli(self):
        chiave = f"ambito__{self.ruolo.id}__copiare"
        request = self.post(self.qualita, self.qualita_l, {chiave: "tutti"})
        self.assertFalse(views._puo_decidere_ambiti(request))
        with patch("timbri.views._can_manage_timbri_config", return_value=True):
            response = views.configurazione_page(request)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(RuoloPermessoModulo.objects.filter(ruolo=self.ruolo, azione="copiare").exists())
        self.assertTrue(AuditLog.objects.filter(azione="timbri_permessi_ambito_denied").exists())

    def test_preset_qualita_copia_e_scarica_tutti(self):
        self.assertTrue(views._can_copy_timbri(self.req(self.qualita, self.qualita_l)))
        self.assertTrue(views._can_download_timbri(self.req(self.qualita, self.qualita_l)))


class SchedeImpostazioniRenderTests(ModuliBase):
    def test_permessi_e_registro_si_aprono(self):
        from django.test import Client

        admin, _ = self.persona("Super", superuser=True)
        from core.models import UserOnboarding

        UserOnboarding.objects.update_or_create(user=admin, defaults={"completed": True})
        client = Client()
        client.force_login(admin)
        for tab, testo in (("permessi", "Chi può copiare e scaricare"), ("registro", "Timbro di")):
            response = client.get("/timbri/impostazioni/", {"tab": tab})
            self.assertEqual(response.status_code, 200, tab)
            self.assertContains(response, testo)
