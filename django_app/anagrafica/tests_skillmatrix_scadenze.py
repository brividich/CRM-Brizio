"""Skill Matrix e scadenze secondo le MT dell'SGI (28/11/2026). Dati sintetici.

- requisiti formali della cella (corso qualificante, qualifica) con scadenza e segno «da sospendere»;
- emissioni del MOD.187: matrice congelata, «da emettere» se cambia, firma Redazione + RDD;
- Scadenzario generale: verifica semestrale per reparto, emissione da approvare, da sospendere;
- efficacia (§9.5): link alla cella della Skill Matrix.
"""
from __future__ import annotations

import io
import shutil
import tempfile
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from assets.models import Asset
from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.models import Profile, UserOnboarding
from timbri.models import CasellaFirma, ImpostazioneFirma, OperatoreTimbri, RegistroTimbro, RegistroTimbroImmagine

from .models import (AbilitazioneMacchina, CompetenzaSkm, DipendenteQualifica, DipendenteRuoloOperativo, EmissioneSkm,
                     Reparto, RuoloOperativo, TipoQualifica, TrainingCourse, TrainingPlan, VoceMacchinaCatalogo)
from .services import skillmatrix_emissioni as em
from .services import skillmatrix_requisiti as req
from .services import skillmatrix_vista as vista
from .tests import _ensure_anagrafica_table

User = get_user_model()


def _png(colore=(20, 40, 160, 255)) -> SimpleUploadedFile:
    buf = io.BytesIO()
    Image.new("RGBA", (40, 16), colore).save(buf, format="PNG")
    return SimpleUploadedFile("img.png", buf.getvalue(), content_type="image/png")


@override_settings(SECURE_SSL_REDIRECT=False, LEGACY_AUTH_ENABLED=False)
class SkillMatrixScadenzeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("sks", "sks@example.invalid", "Prova!2026")
        UserOnboarding.objects.update_or_create(user=self.admin, defaults={"completed": True})
        self.client.force_login(self.admin)
        self.url = reverse("anagrafica:skill_matrix_macchina")
        self.op = AnagraficaDipendente.objects.create(cognome="ROSSI", nome="LUCA", aliasusername="sks.op")
        self.rep = Reparto.objects.create(nome="CND")
        piano = TrainingPlan.objects.create(codice="SKS-P", nome="Piano CND")
        self.corso = TrainingCourse.objects.create(piano=piano, codice="SKS-LP", titolo="Liquidi penetranti base",
                                                   durata_ore_teorica=4)
        a = Asset.objects.create(asset_tag="SKS-LP1", name="Linea LP", asset_type="CND", reparto="CND")
        self.comp = CompetenzaSkm.objects.create(competenza_key="sks_lp", display="Linea LP", tipo="macchina", asset=a,
                                                 corso_qualificante=self.corso)
        self.ab = AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.op.pk, asset=a, competenza=self.comp,
                                                      livello="U")

    # ── requisiti ────────────────────────────────────────────────────────
    def test_corso_qualificante_mancante_da_sospendere(self):
        d = vista.costruisci()
        cella = d["righe"][0]["celle"][0]
        self.assertTrue(cella["da_sospendere"])
        self.assertEqual(cella["req_ko"], ["Liquidi penetranti base"])
        self.assertEqual(d["n_sospendere"], 1)
        self.assertEqual(len(vista.costruisci(solo="sospendere")["righe"]), 1)
        r = self.client.get(reverse("anagrafica:skm_scheda"), {"lid": self.op.pk, "comp": self.comp.pk})
        self.assertContains(r, "Requisiti formali")
        self.assertContains(r, "mancante")
        self.assertContains(r, "Da sospendere")
        r = self.client.get(self.url)
        self.assertContains(r, "Da sospendere")
        # sotto L il corso non serve ancora; sospesa = già gestita
        self.ab.livello = "I"
        self.ab.save()
        self.assertFalse(vista.costruisci()["righe"][0]["celle"][0]["da_sospendere"])

    def test_qualifica_scaduta_con_data(self):
        self.comp.corso_qualificante = None
        self.comp.save()
        tq = TipoQualifica.objects.create(nome="Visita visiva Jaeger T")
        VoceMacchinaCatalogo.objects.create(codice="sks_v1", nome="Ispezione", mansione=self.comp, qualifica=tq)
        scaduta = date.today() - timedelta(days=5)
        DipendenteQualifica.objects.create(legacy_anagrafica_id=self.op.pk, tipo=tq, data_scadenza=scaduta)
        reqs = req.requisiti_colonne([self.comp.pk])[self.comp.pk]
        esito = req.esito_cella(self.op.pk, "U", True, reqs, req.stati([self.op.pk], {self.comp.pk: reqs}, oggi=date.today()))
        self.assertTrue(esito["da_sospendere"])
        self.assertEqual(esito["requisiti"][0]["stato"], req.SCADUTO)
        self.assertEqual(esito["scadenza_ko"], scaduta)

    # ── emissioni ───────────────────────────────────────────────────────
    def test_emissione_senza_firma_e_matrice_cambiata(self):
        ImpostazioneFirma.objects.create(tipo=em.CHIAVE, attiva=False, caselle=[])
        stati = em.stato_reparti(vista.costruisci())
        self.assertTrue(stati["CND"]["modificata"])
        r = self.client.post(reverse("anagrafica:skm_emetti"), {"reparto": "", "data_emissione": "2026-11-28",
                                                                 "nota": "verifica semestrale"})
        e = EmissioneSkm.objects.get()
        self.assertRedirects(r, reverse("anagrafica:skm_emissione", args=[e.pk]), fetch_redirect_response=False)
        self.assertEqual(e.stato, EmissioneSkm.STATO_EMESSA)
        self.assertFalse(em.stato_reparti(vista.costruisci())["CND"]["modificata"])
        self.assertNotContains(self.client.get(self.url), "Matrice cambiata dopo")
        self.ab.livello = "O"
        self.ab.save()
        self.assertTrue(em.stato_reparti(vista.costruisci())["CND"]["modificata"])
        self.assertContains(self.client.get(self.url), "Matrice cambiata dopo")
        r = self.client.get(reverse("anagrafica:skm_emissione_pdf", args=[e.pk]))
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertContains(self.client.get(reverse("anagrafica:skm_emissioni")), "da emettere")

    def test_scadenzario_generale(self):
        from types import SimpleNamespace

        from scadenzario.fonti_moduli import collect_qualifiche
        self.ab.prossima_revisione = date.today() + timedelta(days=10)
        self.ab.save()
        req_ = RequestFactory().get("/")
        req_.user = self.admin
        oggi = date.today()
        ctx = SimpleNamespace(request=req_, oggi=oggi, orizzonte=oggi + timedelta(days=90), sistema=True)
        tipi = {i.kind for i in collect_qualifiche(ctx)}
        self.assertTrue({"abilitazione_macchina", "skm_emissione", "skm_sospendere"} <= tipi)
        sosp = next(i for i in collect_qualifiche(ctx) if i.kind == "skm_sospendere")
        self.assertIn(f"apri={self.op.pk}-{self.comp.pk}", sosp.url)

    def test_link_efficacia(self):
        link = req.link_skill_matrix({(self.op.pk, self.corso.pk)})
        self.assertIn(f"apri={self.op.pk}-{self.comp.pk}", link[(self.op.pk, self.corso.pk)])


@override_settings(SECURE_SSL_REDIRECT=False, LEGACY_AUTH_ENABLED=False)
class EmissioneFirmaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="skm-firma-")
        self._orig = []
        for campo in (RegistroTimbroImmagine._meta.get_field("image"), CasellaFirma._meta.get_field("immagine_firma"),
                      CasellaFirma._meta.get_field("immagine_timbro")):
            st = campo.storage
            self._orig.append((st, dict(st.__dict__)))
            st.__dict__["base_location"] = self.tmp
            st.__dict__["location"] = self.tmp
        rdd = RuoloOperativo.objects.create(nome="Rappresentante della Direzione S", sigla="RDD")
        self.qualita = self._persona("qual.s", "Ivo", "Sala", superuser=True)
        self.rdd = self._persona("rdd.s", "Elena", "Marchi", superuser=True)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=self.rdd.anag_id, ruolo=rdd)
        self._immagini(self.qualita, firma=True)
        self._immagini(self.rdd, firma=True, timbro=True)
        op = AnagraficaDipendente.objects.create(cognome="NERI", nome="ADA", aliasusername="neri.s")
        a = Asset.objects.create(asset_tag="SKS-T1", name="Tornio T1", asset_type="CNC", reparto="TORNI")
        c = CompetenzaSkm.objects.create(competenza_key="sks_t1", display="Tornio T1", tipo="macchina", asset=a)
        AbilitazioneMacchina.objects.create(legacy_anagrafica_id=op.pk, asset=a, competenza=c, livello="U")

    def tearDown(self):
        for st, orig in self._orig:
            st.__dict__.clear()
            st.__dict__.update(orig)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _persona(self, username, nome, cognome, superuser=False):
        legacy = UtenteLegacy.objects.create(nome=f"{cognome} {nome}".upper(), email=f"{username}@example.local",
                                             password="x", attivo=True)
        anag = AnagraficaDipendente.objects.create(nome=nome, cognome=cognome, utente=legacy, aliasusername=username)
        u = User.objects.create_user(username, f"{username}@example.local", "Prova!2026", first_name=cognome,
                                     last_name=nome, is_superuser=superuser, is_staff=superuser)
        Profile.objects.create(user=u, legacy_user_id=legacy.id)
        UserOnboarding.objects.update_or_create(user=u, defaults={"completed": True})
        u.anag_id = anag.id
        return u

    def _immagini(self, user, *, firma=False, timbro=False):
        op = OperatoreTimbri.objects.create(legacy_anagrafica_id=user.anag_id, nome=user.last_name, cognome=user.first_name)
        reg = RegistroTimbro.objects.create(operatore=op, codice_timbro="S1", tipo_timbro=RegistroTimbro.TIPO_FISICO_E_DIGITALE)
        if firma:
            RegistroTimbroImmagine.objects.create(registro=reg, variante="FIRMA", image=_png())
        if timbro:
            RegistroTimbroImmagine.objects.create(registro=reg, variante="TIMBRO", image=_png((200, 30, 30, 255)))

    def test_redazione_poi_approvazione_rdd(self):
        self.client.force_login(self.qualita)
        self.client.post(reverse("anagrafica:skm_emetti"), {
            "reparto": "TORNI", "data_emissione": "2026-11-28", "nota": "nuovo ingresso",
            "scelta": "FIRMA", "segreto": "Prova!2026", "dichiarazione": "1"})
        e = EmissioneSkm.objects.get()
        self.assertEqual(e.stato, EmissioneSkm.STATO_IN_FIRMA)
        self.assertIsNotNone(em.stato_reparti(vista.costruisci())["TORNI"]["in_firma"])
        # un secondo invio sullo stesso reparto è rifiutato finché il primo è in firma
        self.client.post(reverse("anagrafica:skm_emetti"), {"reparto": "TORNI", "scelta": "FIRMA",
                                                             "segreto": "Prova!2026", "dichiarazione": "1"})
        self.assertEqual(EmissioneSkm.objects.count(), 1)
        self.client.force_login(self.rdd)
        r = self.client.get(reverse("anagrafica:skm_emissione", args=[e.pk]))
        self.assertContains(r, "Firma come Approvazione")
        self.client.post(reverse("anagrafica:skm_emissione", args=[e.pk]), {
            "azione": "firma", "scelta": "TIMBRO_FIRMA", "segreto": "Prova!2026", "dichiarazione": "1"})
        e.refresh_from_db()
        self.assertEqual(e.stato, EmissioneSkm.STATO_EMESSA)
        self.assertIn("RDD", e.approvata_da)
        self.assertFalse(em.stato_reparti(vista.costruisci())["TORNI"]["modificata"])
        r = self.client.get(reverse("anagrafica:skm_emissione_pdf", args=[e.pk]))
        self.assertTrue(r.content.startswith(b"%PDF"))
