"""#6 — Sezione Amministrazione: home + CRUD mappatura cliente→cartella + link condizionato."""
import os
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from django.core import mail

from gestione_specifiche import constants as C
from gestione_specifiche.models import (
    AutoApprovazioneConfig, ClienteCartellaShare, EventoSpecifica, MOD133,
    NotificaConfig, Specifica, TimbroApplicazione, TimbroCapocommessa,
)
from gestione_specifiche.notifiche_gs import notifica_nuova_specifica

User = get_user_model()


class AdminSectionTest(TestCase):
    def setUp(self):
        cache.clear()
        self.su = User.objects.create_superuser("adm_su", "a@x.it", "x")
        self.mso = User.objects.create_user("mso_user", "m@x.it", "x", first_name="Mario", last_name="MSO")
        self.client.force_login(self.su)

    def test_home_render(self):
        r = self.client.get(reverse("gestione_specifiche:admin_home"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Amministrazione")
        self.assertContains(r, "Mappatura cliente")

    def test_cartelle_add_edit_delete(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        os.makedirs(os.path.join(root, "DUCATI"))
        with override_settings(GESTIONE_SPECIFICHE_SHARE_ROOTS=[root]):
            r = self.client.get(reverse("gestione_specifiche:admin_cartelle"))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "DUCATI")  # cartella reale nel menu
            r = self.client.post(reverse("gestione_specifiche:admin_cartelle"),
                                 {"cliente": "Ducati", "cartella": "DUCATI"})
            self.assertEqual(r.status_code, 302)

        m = ClienteCartellaShare.objects.get(cliente="Ducati")
        self.assertEqual(m.cartella, "DUCATI")
        self.assertTrue(m.attivo)

        # modifica: senza "attivo" -> disattivata
        r = self.client.post(reverse("gestione_specifiche:admin_cartella_edit", args=[m.pk]),
                             {"cartella": "DUCATI"})
        self.assertEqual(r.status_code, 302)
        m.refresh_from_db()
        self.assertFalse(m.attivo)

        # elimina
        r = self.client.post(reverse("gestione_specifiche:admin_cartella_delete", args=[m.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(ClienteCartellaShare.objects.filter(pk=m.pk).exists())

    def test_link_admin_nel_cruscotto(self):
        r = self.client.get(reverse("gestione_specifiche:lista"))
        self.assertContains(r, "Amministrazione")  # superuser -> permesso admin -> link visibile

    # --- #3 auto-approvazione ---
    def test_config_auto_approva_save(self):
        r = self.client.get(reverse("gestione_specifiche:admin_auto_approva"))
        self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse("gestione_specifiche:admin_auto_approva"),
                             {"attiva": "1", "approvatore": str(self.mso.pk), "nota": "delega"})
        self.assertEqual(r.status_code, 302)
        cfg = AutoApprovazioneConfig.get_config()
        self.assertTrue(cfg.attiva)
        self.assertEqual(cfg.approvatore_id, self.mso.pk)

    def test_attiva_senza_approvatore_rifiutata(self):
        r = self.client.post(reverse("gestione_specifiche:admin_auto_approva"), {"attiva": "1"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(AutoApprovazioneConfig.get_config().attiva)

    def _spec_flow_down(self, codice):
        spec = Specifica.objects.create(codice=codice, titolo="T")
        spec.avvia_flow_down(attore=self.su)
        spec.save()
        return spec

    def test_auto_approvazione_al_procedi(self):
        cfg = AutoApprovazioneConfig.get_config()
        cfg.attiva = True
        cfg.approvatore = self.mso
        cfg.save()
        spec = self._spec_flow_down("SP-AUTO")
        r = self.client.post(reverse("gestione_specifiche:mod133_chiudi", args=[spec.pk]), {"vai": "approva"})
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("gestione_specifiche:dettaglio", args=[spec.pk]), r["Location"])
        spec = Specifica.objects.get(pk=spec.pk)
        self.assertEqual(spec.stato, C.STATO_IN_VALIDITA)  # approvato -> S3
        mod = MOD133.objects.get(specifica=spec)
        self.assertEqual(mod.approvatore_id, self.mso.pk)  # a nome dell'MSO
        self.assertTrue(EventoSpecifica.objects.filter(specifica=spec, trigger="auto_approvazione").exists())

    def test_auto_approvazione_data_fittizia(self):
        from datetime import timedelta

        from gestione_specifiche.date_utils import festivi_it

        cfg = AutoApprovazioneConfig.get_config()
        cfg.attiva = True
        cfg.approvatore = self.mso
        cfg.save()
        spec = self._spec_flow_down("SP-FITT")
        self.client.post(reverse("gestione_specifiche:mod133_chiudi", args=[spec.pk]), {"vai": "approva"})
        mod = MOD133.objects.get(specifica=spec)

        # data_approvazione valorizzata, strettamente dopo la compilazione, in giorno lavorativo
        self.assertIsNotNone(mod.data_approvazione)
        self.assertGreater(mod.data_approvazione, mod.data_chiusura_compilazione)
        d = mod.data_approvazione.date()
        self.assertLess(d.weekday(), 5)
        self.assertNotIn(d, festivi_it(d.year))
        # è almeno il giorno dopo la compilazione
        self.assertGreaterEqual((d - mod.data_chiusura_compilazione.date()), timedelta(days=1))

        # audit onesto: l'evento di transizione mantiene il timestamp reale (≈ adesso, non futuro)
        ev = EventoSpecifica.objects.get(specifica=spec, trigger="approva_flow_down")
        self.assertLess(ev.timestamp, mod.data_approvazione)
        # il marcatore interno porta la data fittizia nel payload
        auto = EventoSpecifica.objects.get(specifica=spec, trigger="auto_approvazione")
        self.assertIn("data_approvazione", auto.payload)

    def test_procedi_senza_auto_va_alla_pagina_approva(self):
        spec = self._spec_flow_down("SP-NOAUTO")  # nessuna config attiva
        r = self.client.post(reverse("gestione_specifiche:mod133_chiudi", args=[spec.pk]), {"vai": "approva"})
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("gestione_specifiche:mod133_approva", args=[spec.pk]), r["Location"])
        self.assertEqual(Specifica.objects.get(pk=spec.pk).stato, C.STATO_FLOW_DOWN)  # NON approvato

    # --- #5 notifiche/assegnazione ---
    def test_config_notifiche_save(self):
        r = self.client.get(reverse("gestione_specifiche:admin_notifiche"))
        self.assertEqual(r.status_code, 200)
        r = self.client.post(reverse("gestione_specifiche:admin_notifiche"),
                             {"reparto_in1": "IN2", "email_attiva": "1",
                              "utenti_aggiuntivi": [str(self.mso.pk)]})
        self.assertEqual(r.status_code, 302)
        cfg = NotificaConfig.get_config()
        self.assertEqual(cfg.reparto_in1, "IN2")
        self.assertTrue(cfg.email_attiva)
        self.assertIn(self.mso.pk, set(cfg.utenti_aggiuntivi.values_list("pk", flat=True)))

    def test_form_nuova_ha_assegna_a(self):
        NotificaConfig.get_config().utenti_aggiuntivi.set([self.mso.pk])
        r = self.client.get(reverse("gestione_specifiche:nuova"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Assegna a")
        self.assertContains(r, "Gruppo IN1")
        self.assertContains(r, "MARIO MSO")  # utente del pool nel menu

    def test_notifica_nuova_specifica_invia_email(self):
        cfg = NotificaConfig.get_config()
        cfg.email_attiva = True
        cfg.save()
        spec = Specifica.objects.create(codice="SP-INC", titolo="T", incaricato=self.mso)
        n = notifica_nuova_specifica(spec)
        self.assertGreaterEqual(n, 1)
        self.assertGreaterEqual(len(mail.outbox), 1)  # email HTML all'incaricato
        self.assertIn("SP-INC", mail.outbox[0].subject)

    def test_notifica_email_disattivata_non_invia(self):
        cfg = NotificaConfig.get_config()
        cfg.email_attiva = False
        cfg.save()
        spec = Specifica.objects.create(codice="SP-NOEMAIL", titolo="T", incaricato=self.mso)
        notifica_nuova_specifica(spec)
        self.assertEqual(len(mail.outbox), 0)

    # --- Log / Audit ---
    def test_admin_log_render_e_filtro(self):
        self._spec_flow_down("SP-LOG")  # genera un evento di transizione
        r = self.client.get(reverse("gestione_specifiche:admin_log"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SP-LOG")
        r = self.client.get(reverse("gestione_specifiche:admin_log"), {"codice": "SP-LOG"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SP-LOG")
        r = self.client.get(reverse("gestione_specifiche:admin_log"), {"codice": "ZZZ-NONE"})
        self.assertNotContains(r, "SP-LOG")

    # --- Gestione specifiche (admin) ---
    def test_admin_specifiche_lista_filtro_riassegna(self):
        s1 = Specifica.objects.create(codice="SP-A", titolo="Alpha", cliente="Ferrari")
        Specifica.objects.create(codice="SP-B", titolo="Beta", cliente="Ducati")
        r = self.client.get(reverse("gestione_specifiche:admin_specifiche"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SP-A")
        self.assertContains(r, "SP-B")
        # ricerca per cliente
        r = self.client.get(reverse("gestione_specifiche:admin_specifiche"), {"q": "Ferrari"})
        self.assertContains(r, "SP-A")
        self.assertNotContains(r, "SP-B")
        # riassegna a una persona
        r = self.client.post(reverse("gestione_specifiche:admin_specifica_riassegna", args=[s1.pk]),
                             {"incaricato": str(self.mso.pk)})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Specifica.objects.get(pk=s1.pk).incaricato_id, self.mso.pk)
        # riassegna al gruppo (vuoto)
        self.client.post(reverse("gestione_specifiche:admin_specifica_riassegna", args=[s1.pk]),
                         {"incaricato": ""})
        self.assertIsNone(Specifica.objects.get(pk=s1.pk).incaricato_id)

    # --- #2 Timbri capocommessa ---
    def test_timbri_upload_e_delete(self):
        from cryptography.fernet import Fernet
        from django.core.files.uploadedfile import SimpleUploadedFile

        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        with override_settings(DOCUMENT_ENCRYPTION_KEY=Fernet.generate_key().decode(),
                               GESTIONE_SPECIFICHE_PRIVATE_ROOT=media):
            r = self.client.get(reverse("gestione_specifiche:admin_timbri"))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "Timbri capocommessa")
            f = SimpleUploadedFile("timbro.png", b"\x89PNG-fake-bytes", content_type="image/png")
            r = self.client.post(reverse("gestione_specifiche:admin_timbri"),
                                 {"codice": "CNOT102", "nome": "Cap. 1", "utente": str(self.mso.pk), "file": f})
            self.assertEqual(r.status_code, 302)
            t = TimbroCapocommessa.objects.get(codice="CNOT102")
            self.assertTrue(t.file.name)
            self.assertEqual(t.utente_id, self.mso.pk)
            r = self.client.post(reverse("gestione_specifiche:admin_timbro_delete", args=[t.pk]))
            self.assertEqual(r.status_code, 302)
            self.assertFalse(TimbroCapocommessa.objects.filter(pk=t.pk).exists())

    def test_applica_timbri_get_render(self):
        spec = self._spec_flow_down("SP-TG")  # senza allegato → mostra errore ma rende
        r = self.client.get(reverse("gestione_specifiche:applica_timbri", args=[spec.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Applica timbri")

    def test_applica_timbri_salva_posizioni(self):
        import json

        from cryptography.fernet import Fernet
        from django.core.files.uploadedfile import SimpleUploadedFile

        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        with override_settings(DOCUMENT_ENCRYPTION_KEY=Fernet.generate_key().decode(),
                               GESTIONE_SPECIFICHE_PRIVATE_ROOT=media):
            f = SimpleUploadedFile("t.png", b"\x89PNG-fake", content_type="image/png")
            # Il timbro appartiene a chi compila (qui l'utente loggato: MOD.133 senza compilatore).
            self.client.post(reverse("gestione_specifiche:admin_timbri"),
                             {"codice": "CNOT1", "tipo": "ricevuto", "utente": str(self.su.pk), "file": f})
            t = TimbroCapocommessa.objects.get(codice="CNOT1")
            spec = self._spec_flow_down("SP-TIMB")  # crea MOD.133 (0 righe → n_mod133=1)
            r = self.client.post(
                reverse("gestione_specifiche:applica_timbri", args=[spec.pk]),
                data=json.dumps({"placements": [
                    {"timbro": t.pk, "page": 0, "x": 10, "y": 20, "w": 100},
                    {"timbro": t.pk, "page": 1, "x": 30, "y": 40, "w": 120}]}),
                content_type="application/json")
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["ok"])
        apps = list(TimbroApplicazione.objects.filter(specifica=spec))
        self.assertEqual(len(apps), 2)
        sez = {a.sezione: a for a in apps}
        self.assertIn("mod133", sez)       # page 0 → MOD.133
        self.assertIn("originale", sez)    # page 1 → originale
        self.assertEqual(sez["originale"].pagina, 0)  # 1 - n_mod133(1)
        self.assertEqual(sez["mod133"].pagina, 0)
        evento = EventoSpecifica.objects.filter(specifica=spec, trigger="timbri_applicati").get()
        self.assertEqual(evento.attore_id, self.su.pk)
        self.assertEqual(evento.payload["n"], 2)

    # --- Applica timbri: solo i timbri delle persone del MOD.133 ---
    def _timbro(self, codice, utente, tipo="ricevuto"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return TimbroCapocommessa.objects.create(
            codice=codice, tipo=tipo, utente=utente,
            file=SimpleUploadedFile(f"{codice}.png", b"\x89PNG-fake", content_type="image/png"))

    def _media_ctx(self):
        from cryptography.fernet import Fernet

        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        return override_settings(DOCUMENT_ENCRYPTION_KEY=Fernet.generate_key().decode(),
                                 GESTIONE_SPECIFICHE_PRIVATE_ROOT=media)

    def _post_placements(self, spec, placements):
        import json

        return self.client.post(reverse("gestione_specifiche:applica_timbri", args=[spec.pk]),
                                data=json.dumps({"placements": placements}), content_type="application/json")

    def test_applica_timbri_rifiuta_timbro_di_altra_persona(self):
        with self._media_ctx():
            altrui = self._timbro("CNOT-ALTRO", self.mso)
            spec = self._spec_flow_down("SP-ALTRUI")
            r = self._post_placements(spec, [{"timbro": altrui.pk, "page": 0, "x": 1, "y": 1, "w": 100}])
            self.assertEqual(r.status_code, 403)
            self.assertFalse(r.json()["ok"])
            self.assertFalse(TimbroApplicazione.objects.filter(specifica=spec).exists())
            self.assertFalse(EventoSpecifica.objects.filter(specifica=spec, trigger="timbri_applicati").exists())

    def test_applica_timbri_palette_mostra_solo_timbri_ammessi(self):
        with self._media_ctx():
            self._timbro("CNOT-MIO", self.su)
            self._timbro("CNOT-ALTRO", self.mso)
            spec = self._spec_flow_down("SP-PAL")
            from gestione_specifiche.timbri_views import timbri_ammessi

            codici = set(timbri_ammessi(spec, self.su).values_list("codice", flat=True))
            self.assertEqual(codici, {"CNOT-MIO"})

    def test_firma_approvatore_solo_dopo_approvazione(self):
        with self._media_ctx():
            firma_appr = self._timbro("CNOT-APPR", self.mso, tipo="mod133")
            ricevuto_appr = self._timbro("CNOT-APPR-R", self.mso, tipo="ricevuto")
            spec = self._spec_flow_down("SP-APPR")
            from gestione_specifiche.timbri_views import timbri_ammessi

            self.assertNotIn(firma_appr.pk, set(timbri_ammessi(spec, self.su).values_list("pk", flat=True)))
            mod = spec.mod133
            mod.compilatore = self.su
            mod.approvatore = self.mso
            mod.save()
            spec = Specifica.objects.get(pk=spec.pk)
            ammessi = set(timbri_ammessi(spec, self.su).values_list("pk", flat=True))
            self.assertIn(firma_appr.pk, ammessi)
            # Dell'approvatore vale solo la firma MOD.133, non il suo RICEVUTO.
            self.assertNotIn(ricevuto_appr.pk, ammessi)

    def test_applica_timbri_payload_malformato_400(self):
        with self._media_ctx():
            t = self._timbro("CNOT-OK", self.su)
            spec = self._spec_flow_down("SP-BAD")
            for bad in ([{"timbro": "x", "page": 0}], [{"timbro": t.pk, "page": -1}],
                        [{"timbro": t.pk, "page": 0, "x": "nan"}], ["stringa"]):
                r = self._post_placements(spec, bad)
                self.assertEqual(r.status_code, 400, bad)
            r = self.client.post(reverse("gestione_specifiche:applica_timbri", args=[spec.pk]),
                                 data="[1, 2]", content_type="application/json")
            self.assertEqual(r.status_code, 400)

    def test_composito_non_stampa_timbri_non_ammessi(self):
        from gestione_specifiche.composito import _risolvi_placements

        with self._media_ctx():
            mio = self._timbro("CNOT-COMP", self.su)
            altrui = self._timbro("CNOT-INTRUSO", self.mso)
            spec = self._spec_flow_down("SP-COMP")
            mod = spec.mod133
            mod.compilatore = self.su
            mod.save()
            TimbroApplicazione.objects.create(specifica=spec, timbro=mio, sezione="originale", pagina=0)
            TimbroApplicazione.objects.create(specifica=spec, timbro=altrui, sezione="originale", pagina=0)
            spec = Specifica.objects.get(pk=spec.pk)
            out = _risolvi_placements(spec) or []
            self.assertEqual(len(out), 1)
            mio.attivo = False
            mio.save()
            self.assertIsNone(_risolvi_placements(spec))
