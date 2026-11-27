"""Organigramma ufficiale con firma su portale (MT CN 08 §7.2.1): Redazione + Approvazione RDD.

Dati sintetici: persone, ruoli e immagini inventati.
"""
import io
import shutil
import tempfile
from datetime import date

from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from anagrafica.models import DipendenteRuoloOperativo, OrganigrammaRevisione, OrganigrammaUfficiale, RuoloOperativo
from core.legacy_models import AnagraficaDipendente, UtenteLegacy
from core.models import Notifica, Profile, UserOnboarding
from timbri import firme
from timbri.models import (
    CasellaFirma,
    DocumentoFirma,
    ImpostazioneFirma,
    OperatoreTimbri,
    RegistroTimbro,
    RegistroTimbroImmagine,
)

User = get_user_model()


def _png(colore=(20, 40, 160, 255)) -> SimpleUploadedFile:
    buf = io.BytesIO()
    Image.new("RGBA", (40, 16), colore).save(buf, format="PNG")
    return SimpleUploadedFile("img.png", buf.getvalue(), content_type="image/png")


def _box(nid, **kw):
    n = {"id": nid, "tipo": "box", "x": 0, "y": 0, "w": 220, "h": 60}
    n.update(kw)
    return n


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class FirmaOrganigrammaTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="firma-test-")
        self._storage_orig = []
        for campo in (RegistroTimbroImmagine._meta.get_field("image"), CasellaFirma._meta.get_field("immagine_firma"),
                      CasellaFirma._meta.get_field("immagine_timbro")):
            st = campo.storage
            self._storage_orig.append((st, dict(st.__dict__)))
            st.__dict__["base_location"] = self.tmp
            st.__dict__["location"] = self.tmp
        self.rdd = RuoloOperativo.objects.create(nome="Rappresentante della Direzione T", sigla="RDD")
        self.redattore = self._persona("redattore.t", "Ivo", "Sala", superuser=True)
        self.capo = self._persona("rdd.t", "Elena", "Marchi")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=self.capo.anag_id, ruolo=self.rdd)
        self.estraneo = self._persona("altro.t", "Piero", "Gatti")
        self._immagini(self.redattore, firma=True)
        self._immagini(self.capo, firma=True, timbro=True, codice="CNO Q207")
        self.org = OrganigrammaUfficiale.objects.create(nome="Aziendale T", bozza={"nodi": [_box("a", titolo="Direzione")]})

    def tearDown(self):
        for st, orig in self._storage_orig:
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
        u.legacy_id = legacy.id
        return u

    def _immagini(self, user, *, firma=False, timbro=False, codice=""):
        op = OperatoreTimbri.objects.create(legacy_anagrafica_id=user.anag_id, nome=user.last_name, cognome=user.first_name)
        reg = RegistroTimbro.objects.create(operatore=op, codice_timbro=codice, tipo_timbro=RegistroTimbro.TIPO_FISICO_E_DIGITALE)
        if firma:
            RegistroTimbroImmagine.objects.create(registro=reg, variante="FIRMA", image=_png())
        if timbro:
            RegistroTimbroImmagine.objects.create(registro=reg, variante="TIMBRO", image=_png((200, 30, 30, 255)))
        return reg

    def _invia(self, **extra):
        self.client.force_login(self.redattore)
        dati = {"nota": "Nuovo reparto", "data_emissione": "2026-11-27", "scelta": "FIRMA",
                "segreto": "Prova!2026", "dichiarazione": "1"}
        dati.update(extra)
        return self.client.post(reverse("anagrafica:organigramma_ufficiale_invia", args=[self.org.pk]), dati)

    def _firma_rdd(self, **extra):
        self.client.force_login(self.capo)
        dati = {"azione": "firma", "scelta": "TIMBRO_FIRMA", "segreto": "Prova!2026", "dichiarazione": "1"}
        dati.update(extra)
        return self.client.post(reverse("anagrafica:organigramma_ufficiale_firma", args=[self.org.pk]), dati)

    # ── regole di serie ───────────────────────────────────────────────────

    def test_di_serie_redazione_di_chi_invia_e_approvazione_rdd(self):
        imp = firme.impostazione("organigramma_ufficiale")
        self.assertTrue(imp["attiva"])
        self.assertEqual([(c["etichetta"], c["mittente"], c["ruolo_sigla"]) for c in imp["caselle"]],
                         [("Redazione", True, ""), ("Approvazione", False, "RDD")])

    def test_pubblica_diretta_rifiutata_con_firma_accesa(self):
        self.client.force_login(self.redattore)
        self.client.post(reverse("anagrafica:organigramma_ufficiale_pubblica", args=[self.org.pk]),
                         {"approvato_da": "Chiunque", "data_emissione": "2026-11-27"})
        self.assertFalse(OrganigrammaRevisione.objects.exists())

    # ── flusso completo ───────────────────────────────────────────────────

    def test_invio_firma_rdd_crea_la_revisione(self):
        r = self._invia()
        self.assertRedirects(r, reverse("anagrafica:organigramma_ufficiale_firma", args=[self.org.pk]),
                             fetch_redirect_response=False)
        doc = DocumentoFirma.objects.get()
        self.assertEqual(doc.stato, DocumentoFirma.STATO_IN_FIRMA)
        red, app = list(doc.caselle.all())
        self.assertEqual((red.stato, red.firmata_da, red.conferma), ("FIRMATA", self.redattore, "password"))
        self.assertTrue(red.immagine_firma)
        self.assertEqual(app.stato, "ATTESA")
        self.assertEqual(len(doc.impronta), 64)
        # RDD riceve la notifica, la revisione non esiste ancora
        self.assertTrue(Notifica.objects.filter(legacy_user_id=self.capo.legacy_id, tipo="firma_da_apporre").exists())
        self.assertFalse(OrganigrammaRevisione.objects.exists())
        # la bozza è congelata
        r = self.client.post(reverse("anagrafica:organigramma_ufficiale_bozza", args=[self.org.pk]),
                             '{"disegno": {"nodi": []}}', content_type="application/json")
        self.assertEqual(r.status_code, 409)

        r = self._firma_rdd()
        self.assertRedirects(r, reverse("anagrafica:organigramma_ufficiale_vedi", args=[self.org.pk]),
                             fetch_redirect_response=False)
        doc.refresh_from_db()
        self.assertEqual(doc.stato, DocumentoFirma.STATO_FIRMATO)
        rev = OrganigrammaRevisione.objects.get()
        self.assertEqual((rev.numero, rev.data_emissione, rev.nota), (1, date(2026, 11, 27), "Nuovo reparto"))
        self.assertEqual(rev.approvato_da, "MARCHI ELENA (RDD)")
        self.assertEqual(doc.esito_id, rev.pk)
        app = doc.caselle.get(ordine=2)
        self.assertTrue(app.immagine_firma and app.immagine_timbro)
        self.assertEqual(app.codice_timbro, "CNO Q207")
        self.org.refresh_from_db()
        self.assertIsNone(self.org.bozza)

        # stampa e versione in vigore mostrano le firme
        r = self.client.get(reverse("anagrafica:organigramma_ufficiale_stampa", args=[self.org.pk]))
        self.assertContains(r, doc.codice_verifica)
        self.assertContains(r, reverse("anagrafica:organigramma_ufficiale_firma_immagine", args=[app.pk, "timbro"]))
        r = self.client.get(reverse("anagrafica:organigramma_ufficiale_vedi", args=[self.org.pk]))
        self.assertContains(r, "Firme della Rev.1")
        # immagine firmata: visibile a chi vede l'organigramma
        self.client.force_login(self.estraneo)
        r = self.client.get(reverse("anagrafica:organigramma_ufficiale_firma_immagine", args=[app.pk, "firma"]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/png")

    # ── chi firma e con cosa ──────────────────────────────────────────────

    def test_chi_non_ha_il_ruolo_non_firma_e_non_vede(self):
        self._invia()
        self.client.force_login(self.estraneo)
        r = self.client.get(reverse("anagrafica:organigramma_ufficiale_firma", args=[self.org.pk]))
        self.assertEqual(r.status_code, 404)
        self.client.post(reverse("anagrafica:organigramma_ufficiale_firma", args=[self.org.pk]),
                         {"azione": "firma", "scelta": "FIRMA", "segreto": "Prova!2026", "dichiarazione": "1"})
        self.assertEqual(DocumentoFirma.objects.get().stato, DocumentoFirma.STATO_IN_FIRMA)
        self.assertFalse(OrganigrammaRevisione.objects.exists())

    def test_password_sbagliata_o_senza_dichiarazione_non_firma(self):
        self._invia()
        self._firma_rdd(segreto="sbagliata")
        self._firma_rdd(dichiarazione="")
        self.assertEqual(DocumentoFirma.objects.get().caselle.get(ordine=2).stato, "ATTESA")

    def test_si_firma_solo_con_le_proprie_immagini(self):
        """Il redattore ha solo la firma: non può scegliere un timbro, e non vede mai quelli degli altri."""
        doc_opz = firme.opzioni(self.redattore, CasellaFirma(varianti="FIRMA,TIMBRO"))
        per_chiave = {o["chiave"]: o for o in doc_opz}
        self.assertTrue(per_chiave["FIRMA"]["disponibile"])
        self.assertFalse(per_chiave["TIMBRO"]["disponibile"])
        proprie_capo = {i.pk for i in firme.immagini_proprie(self.capo).values()}
        self.assertFalse(proprie_capo & {i.pk for o in doc_opz for i in o["immagini"]})
        # anteprima: la propria sì, quella di un altro no
        mia = firme.immagini_proprie(self.redattore)["FIRMA"]
        altrui = firme.immagini_proprie(self.capo)["FIRMA"]
        self.client.force_login(self.redattore)
        self.assertEqual(self.client.get(reverse("anagrafica:organigramma_ufficiale_mia_immagine", args=[mia.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("anagrafica:organigramma_ufficiale_mia_immagine", args=[altrui.pk])).status_code, 404)

    def test_timbro_sospeso_o_ritirato_non_si_usa(self):
        reg = RegistroTimbro.objects.get(operatore__legacy_anagrafica_id=self.capo.anag_id)
        reg.is_sospeso = True
        reg.save()
        self.assertEqual(firme.immagini_proprie(self.capo), {})

    def test_stessa_persona_non_firma_due_caselle(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=self.redattore.anag_id, ruolo=self.rdd)
        self._invia()
        self.client.post(reverse("anagrafica:organigramma_ufficiale_firma", args=[self.org.pk]),
                         {"azione": "firma", "scelta": "FIRMA", "segreto": "Prova!2026", "dichiarazione": "1"})
        self.assertEqual(DocumentoFirma.objects.get().caselle.get(ordine=2).stato, "ATTESA")

    def test_senza_titolari_rdd_l_invio_e_bloccato(self):
        DipendenteRuoloOperativo.objects.all().delete()
        self._invia()
        self.assertFalse(DocumentoFirma.objects.exists())

    def test_contenuto_alterato_blocca_la_firma(self):
        self._invia()
        doc = DocumentoFirma.objects.get()
        doc.contenuto["dati"]["nodi"] = []
        doc.save(update_fields=["contenuto"])
        self._firma_rdd()
        self.assertEqual(DocumentoFirma.objects.get().stato, DocumentoFirma.STATO_IN_FIRMA)

    # ── respingi e ritira ─────────────────────────────────────────────────

    def test_rdd_respinge_con_motivo_e_la_bozza_torna_modificabile(self):
        self._invia()
        self.client.force_login(self.capo)
        url = reverse("anagrafica:organigramma_ufficiale_firma", args=[self.org.pk])
        self.client.post(url, {"azione": "respingi", "motivo": ""})
        self.assertEqual(DocumentoFirma.objects.get().stato, DocumentoFirma.STATO_IN_FIRMA)
        self.client.post(url, {"azione": "respingi", "motivo": "Manca il preposto"})
        doc = DocumentoFirma.objects.get()
        self.assertEqual((doc.stato, doc.motivo), (DocumentoFirma.STATO_RESPINTO, "Manca il preposto"))
        self.assertTrue(Notifica.objects.filter(legacy_user_id=self.redattore.legacy_id, tipo="firma_respinta").exists())
        self.client.force_login(self.redattore)
        r = self.client.get(reverse("anagrafica:organigramma_ufficiale_disegna", args=[self.org.pk]))
        self.assertEqual(r.status_code, 200)

    def test_ritira_sblocca_la_bozza(self):
        self._invia()
        r = self.client.post(reverse("anagrafica:organigramma_ufficiale_firma", args=[self.org.pk]), {"azione": "ritira"})
        self.assertRedirects(r, reverse("anagrafica:organigramma_ufficiale_disegna", args=[self.org.pk]),
                             fetch_redirect_response=False)
        self.assertEqual(DocumentoFirma.objects.get().stato, DocumentoFirma.STATO_RITIRATO)

    # ── impostazioni ──────────────────────────────────────────────────────

    def test_impostazioni_spente_tornano_alla_pubblicazione_diretta(self):
        self.client.force_login(self.redattore)
        self.client.post(reverse("anagrafica:organigramma_ufficiale_firme_impostazioni"), {})
        self.assertFalse(ImpostazioneFirma.objects.get().attiva)
        self.client.post(reverse("anagrafica:organigramma_ufficiale_pubblica", args=[self.org.pk]),
                         {"approvato_da": "Direzione", "data_emissione": "2026-11-27"})
        self.assertEqual(OrganigrammaRevisione.objects.get().approvato_da, "Direzione")

    def test_impostazioni_solo_amministratori(self):
        self.client.force_login(self.capo)
        self.client.post(reverse("anagrafica:organigramma_ufficiale_firme_impostazioni"), {})
        self.assertFalse(ImpostazioneFirma.objects.exists())

    def test_elenco_mostra_da_firmare_a_rdd(self):
        self._invia()
        self.client.force_login(self.capo)
        r = self.client.get(reverse("anagrafica:organigramma_ufficiale"))
        self.assertContains(r, "Apri e firma")
        r = self.client.get(reverse("anagrafica:organigramma_ufficiale_firma", args=[self.org.pk]))
        self.assertContains(r, "Firma come Approvazione")
        self.assertContains(r, "Respingi")
