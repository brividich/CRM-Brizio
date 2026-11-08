"""Reception nell'HUB: regole, letture uguali al GuestPortal, chiosco, pannello, pulizia, importazione."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import Fornitore
from fornitori import guestportal as gp
from fornitori import tasks as fornitori_tasks

from . import letture, servizi, tasks
from .models import Cartellino, CategoriaVisita, ContattoDitta, DittaAccreditata, EventoVisita, Ospite, Preregistrazione, Referente, Visita


class Base(TestCase):
    def setUp(self):
        cache.clear()
        for n in ("01", "02"):
            Cartellino.objects.create(numero=n)
        self.ref = Referente.objects.create(nome="Prova", cognome="Referente", email="referente@example.local", reparto="IT")
        CategoriaVisita.objects.create(nome="Altro", icona="📋")
        self.ospite = servizi.ospite_da_dati(nome="Mario", cognome="Esempio", email="m@example.local", azienda="Ditta Prova")

    def entra(self, ospite=None, **kw):
        return servizi.registra_ingresso(ospite or self.ospite, referente_nome="Referente Prova", **kw)


class RegoleTests(Base):
    def test_ingresso_prende_il_primo_cartellino_libero(self):
        v = self.entra()
        self.assertEqual(v.cartellino, "01")
        self.assertFalse(Cartellino.objects.get(numero="01").disponibile)

    def test_doppio_ingresso(self):
        self.entra()
        with self.assertRaises(servizi.GiaDentro):
            self.entra()

    def test_cartellini_finiti_non_crea_la_visita(self):
        Cartellino.objects.update(disponibile=False)
        with self.assertRaises(servizi.CartelliniFiniti):
            self.entra()
        self.assertFalse(Visita.objects.exists())

    def test_email_di_un_altro(self):
        with self.assertRaises(servizi.EmailDiAltri):
            servizi.ospite_da_dati(nome="Altra", cognome="Persona", email="M@example.local")

    def test_uscita_libera_il_cartellino(self):
        v = self.entra()
        servizi.registra_uscita(v.pk, cartellino="1")
        v.refresh_from_db()
        self.assertEqual(v.stato, Visita.USCITO)
        self.assertTrue(Cartellino.objects.get(numero="01").disponibile)
        self.assertFalse(EventoVisita.objects.exists())

    def test_uscita_col_cartellino_sbagliato(self):
        v = self.entra()
        with self.assertRaises(servizi.OperazioneNonValida):
            servizi.registra_uscita(v.pk, cartellino="02")

    def test_correzione_uscita_regole_e_traccia(self):
        v = self.entra(quando=timezone.now() - timedelta(hours=3))
        with self.assertRaises(servizi.OperazioneNonValida):
            servizi.correggi_uscita(v.pk, v.ingresso - timedelta(hours=1))
        with self.assertRaises(servizi.OperazioneNonValida):
            servizi.correggi_uscita(v.pk, timezone.now() + timedelta(hours=1))
        servizi.correggi_uscita(v.pk, timezone.now() - timedelta(hours=1), autore="operatore")
        self.assertEqual(EventoVisita.objects.get().autore, "operatore")

    def test_riapertura(self):
        v = self.entra()
        with self.assertRaises(servizi.OperazioneNonValida):
            servizi.riapri_visita(v.pk, "02")
        servizi.registra_uscita(v.pk)
        servizi.riapri_visita(v.pk, "02")
        v.refresh_from_db()
        self.assertEqual((v.stato, v.cartellino), (Visita.DENTRO, "02"))

    def test_riapertura_troppo_vecchia(self):
        v = self.entra(quando=timezone.now() - timedelta(days=9))
        servizi.registra_uscita(v.pk)
        with self.assertRaises(servizi.OperazioneNonValida):
            servizi.riapri_visita(v.pk, "01")

    def test_codice_una_volta_sola(self):
        p = Preregistrazione.objects.create(codice="ABCD2345", ospite_nome="Anna Prova", referente_nome="R", scade_il=timezone.now() + timedelta(days=1))
        self.assertEqual(servizi.ingresso_da_codice("abcd2345").tipo, Visita.PREREG)
        p.refresh_from_db()
        self.assertIsNotNone(p.usata_il)
        self.assertIsNone(servizi.ingresso_da_codice("ABCD2345"))

    def test_codice_con_cartellini_finiti_resta_valido(self):
        Cartellino.objects.update(disponibile=False)
        p = Preregistrazione.objects.create(codice="ABCD2345", ospite_nome="Anna Prova", referente_nome="R", scade_il=timezone.now() + timedelta(days=1))
        with self.assertRaises(servizi.CartelliniFiniti):
            servizi.ingresso_da_codice("ABCD2345")
        p.refresh_from_db()
        self.assertIsNone(p.usata_il)


class PuliziaTests(Base):
    def test_cancella_solo_oltre_il_termine(self):
        vecchia = self.entra(quando=timezone.now() - timedelta(days=400))
        servizi.registra_uscita(vecchia.pk)
        altro = servizi.ospite_da_dati(nome="Luisa", cognome="Prova")
        recente = self.entra(ospite=altro, quando=timezone.now() - timedelta(days=10))
        Ospite.objects.filter(pk=self.ospite.pk).update(creato_il=timezone.now() - timedelta(days=400))
        esito = servizi.pulizia_conservazione(12)
        self.assertEqual(esito["visite"], 1)
        self.assertFalse(Visita.objects.filter(pk=vecchia.pk).exists())
        self.assertFalse(Ospite.objects.filter(pk=self.ospite.pk).exists())
        self.assertTrue(Visita.objects.filter(pk=recente.pk).exists())

    def test_chi_e_dentro_non_si_cancella(self):
        v = self.entra(quando=timezone.now() - timedelta(days=400))
        self.assertEqual(servizi.pulizia_conservazione(12)["visite"], 0)
        self.assertTrue(Visita.objects.filter(pk=v.pk).exists())

    @override_settings(RECEPTION_NATIVA=False)
    def test_spenta_non_tocca_niente(self):
        self.assertIn("saltato", tasks.run_pulizia())
        self.assertIn("saltato", tasks.run_avvisi_referenti())


class MailTests(Base):
    def test_avviso_una_volta_sola(self):
        v = self.entra(referente_email="referente@example.local")
        with patch("core.email_utils.send_hub_mail") as invia:
            self.assertEqual(tasks.invia_avvisi_referenti()["inviate"], 1)
            self.assertEqual(tasks.invia_avvisi_referenti()["inviate"], 0)
        self.assertEqual(invia.call_count, 1)
        v.refresh_from_db()
        self.assertEqual(v.mail_stato, Visita.MAIL_INVIATA)

    def test_mail_fallita_non_ferma_le_altre(self):
        v = self.entra(referente_email="referente@example.local")
        with patch("core.email_utils.send_hub_mail", side_effect=OSError):
            self.assertEqual(tasks.invia_avvisi_referenti()["fallite"], 1)
        v.refresh_from_db()
        self.assertEqual(v.mail_stato, Visita.MAIL_FALLITA)

    def test_invito_con_qr_e_calendario(self):
        from . import mail

        p = Preregistrazione.objects.create(codice="ABCD2345", ospite_nome="Anna Prova", ospite_email="a@example.local",
                                            referente_nome="R", referente_email="r@example.local",
                                            scade_il=timezone.now() + timedelta(days=1), data_visita=date(2026, 12, 1), ora_inizio=time(9, 0))
        with patch("core.email_utils.send_hub_mail") as invia:
            mail.invia_invito(p)
        self.assertEqual(invia.call_count, 2)
        allegati = invia.call_args_list[0].kwargs["attachments"]
        self.assertEqual([a[0] for a in allegati], ["codice-accesso.png", "invito.ics"])
        self.assertIn("DTSTART;TZID=Europe/Rome:20261201T090000", allegati[1][1])


@override_settings(RECEPTION_NATIVA=True)
class LettureTests(Base):
    def test_gli_stessi_tipi_del_guestportal(self):
        v = self.entra(motivo="Altro")
        self.assertTrue(gp.db_configurato())
        presenti = gp.presenti_ora()
        self.assertEqual(presenti[0].visita_id, v.pk)
        self.assertEqual(presenti[0].nome, "Mario Esempio")
        self.assertEqual(presenti[0].azienda, "Ditta Prova")
        self.assertIsNone(presenti[0].ingresso.tzinfo)
        self.assertEqual(gp.visita(v.pk).badge, "01")
        self.assertIsNone(gp.visita(999))

    def test_storico_filtra_e_taglia(self):
        for i in range(3):
            o = servizi.ospite_da_dati(nome=f"N{i}", cognome="Prova")
            v = servizi.registra_ingresso(o, referente_nome="R", cartellino="")
            self.assertEqual(v.cartellino, "N/A")
        oggi = timezone.localdate()
        righe, tagliato = gp.storico(dal=oggi, al=oggi, limite=2)
        self.assertEqual((len(righe), tagliato), (2, True))
        self.assertEqual(len(gp.storico(dal=oggi, al=oggi, testo="N1")[0]), 1)
        self.assertEqual(gp.storico(dal=oggi - timedelta(days=9), al=oggi - timedelta(days=5))[0], [])

    def test_ingressi_e_tecnici_di_una_ditta(self):
        d = DittaAccreditata.objects.create(nome="Impianti Esempio Srl")
        c = ContattoDitta.objects.create(ditta=d, nome="Mario", cognome="Esempio")
        v = self.entra(tipo=Visita.FORNITORE, ditta=d, contatto=c, quando=timezone.now() - timedelta(hours=2))
        servizi.registra_uscita(v.pk)
        oggi = timezone.localdate(v.ingresso)  # il giorno dell'ingresso: fra le 00 e le 02 «2 ore fa» è ieri
        self.assertEqual(len(gp.ingressi_ditta(ditte_gp=[d.pk], nomi=[], dal=oggi, al=oggi)), 1)
        self.assertEqual(len(gp.ingressi_ditta(ditte_gp=[], nomi=["impianti esempio srl"], dal=oggi, al=oggi)), 1)
        self.assertEqual(gp.ingressi_ditta(ditte_gp=[], nomi=[], dal=oggi, al=oggi), [])
        tecnici, _ = gp.tecnici_ditta(ditte_gp=[d.pk], nomi=[])
        self.assertEqual(tecnici[0].ingressi, 1)
        self.assertGreaterEqual(tecnici[0].minuti, 119)
        self.assertEqual(gp.ditte_guestportal(), [(d.pk, "Impianti Esempio Srl")])

    def test_anonimizzato_non_mostra_dati(self):
        Ospite.objects.filter(pk=self.ospite.pk).update(anonimizzato=True)
        self.entra()
        a = gp.presenti_ora()[0]
        self.assertEqual((a.nome, a.azienda), ("Ospite anonimizzato", ""))


@override_settings(RECEPTION_NATIVA=True, CHIOSCO_ALLOWED_IPS=["127.0.0.1"], SECURE_SSL_REDIRECT=False)
class ChioscoNativoTests(Base):
    def api(self, azione, **dati):
        return self.client.post(reverse("chiosco:api", args=[azione]), json.dumps(dati), content_type="application/json")

    def test_pagina_con_i_referenti_dell_hub(self):
        r = self.client.get(reverse("chiosco:pagina"))
        self.assertContains(r, "Referente Prova")
        self.assertNotContains(r, "referente@example.local")

    def test_giro_completo(self):
        r = self.api("ingresso", first_name="Luisa", last_name="Prova", referente_id=self.ref.pk, motivo="Altro", gdpr_consent=True,
                     email="l@example.local")
        self.assertEqual(r.json()["badge_number"], "01")
        v = Visita.objects.get()
        self.assertEqual(v.referente_email, "referente@example.local")
        self.assertEqual(v.ospite.informativa_ip, "127.0.0.1")
        self.assertTrue(self.api("ingresso", first_name="Luisa", last_name="Prova", referente_id=self.ref.pk, motivo="Altro",
                                 gdpr_consent=True, email="l@example.local").json()["already_in"])
        trovata = self.api("cerca-uscita", badge="1").json()["visits"][0]
        self.assertEqual(trovata["visit_id"], v.pk)
        self.assertTrue(self.api("uscita", visit_id=v.pk, badge="01").json()["success"])
        self.assertFalse(self.api("uscita", visit_id=v.pk, badge="01").json()["success"])

    def test_email_di_altri_non_rivela_il_nome(self):
        r = self.api("ingresso", first_name="Altra", last_name="Persona", referente_id=self.ref.pk, motivo="Altro", gdpr_consent=True,
                     email="m@example.local")
        self.assertNotIn("Mario", r.content.decode())
        self.assertFalse(r.json()["success"])

    def test_fornitore(self):
        d = DittaAccreditata.objects.create(nome="Impianti Esempio Srl")
        c = ContattoDitta.objects.create(ditta=d, nome="Mario", cognome="Esempio")
        self.assertEqual(self.api("aziende").json()["aziende"][0]["id"], d.pk)
        self.assertEqual(self.api("nominativi", azienda_id=d.pk).json()["nominativi"][0]["id"], c.pk)
        r = self.api("ingresso-fornitore", azienda_id=d.pk, nominativo_id=c.pk, referente_id=self.ref.pk, gdpr_consent=True)
        self.assertTrue(r.json()["success"])
        v = Visita.objects.get()
        self.assertEqual((v.tipo, v.ditta_id, v.motivo), (Visita.FORNITORE, d.pk, "Impianti Esempio Srl"))

    def test_codice(self):
        Preregistrazione.objects.create(codice="ABCD2345", ospite_nome="Anna Prova", referente_nome="R", motivo="Altro", scade_il=timezone.now() + timedelta(days=1))
        self.assertEqual(self.api("prereg-cerca", code="abcd2345").json()["prereg"]["guest_name"], "Anna Prova")
        self.assertEqual(self.api("prereg-entra", code="ABCD2345", gdpr_consent=True).json()["badge_number"], "01")
        self.assertFalse(self.api("prereg-entra", code="ABCD2345", gdpr_consent=True).json()["success"])
        self.assertFalse(self.api("prereg-cerca", code="ABCD2345").json()["success"])

    def _ingresso_ditta_non_in_regola(self):
        Fornitore.objects.create(ragione_sociale="Ditta Prova", accede_in_sede=True)
        return self.api("ingresso", first_name="Luisa", last_name="Prova", company="Ditta Prova", referente_id=self.ref.pk,
                        motivo="Altro", gdpr_consent=True)

    def test_avviso_requisiti_spento_di_default(self):
        self.assertNotIn("passa_reception", self._ingresso_ditta_non_in_regola().json())

    def test_avviso_requisiti_acceso_non_blocca(self):
        from core.models import SiteConfig

        SiteConfig.set("chiosco_avviso_requisiti", "1")
        r = self._ingresso_ditta_non_in_regola().json()
        self.assertTrue(r["success"])
        self.assertTrue(r["passa_reception"])


class PannelloTests(Base):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_superuser("adm_rc", "adm@example.local", "x")
        self.client.force_login(self.user)

    def test_login_obbligatorio(self):
        self.client.logout()
        for nome in ("cruscotto", "registra", "storico", "preregistrazioni", "referenti", "ditte", "cartellini", "impostazioni"):
            self.assertEqual(self.client.get(reverse(f"reception:{nome}")).status_code, 302, nome)

    def test_tutte_le_pagine_si_aprono(self):
        v = self.entra()
        for nome in ("cruscotto", "registra", "storico", "preregistrazioni", "referenti", "ditte", "cartellini", "impostazioni"):
            self.assertEqual(self.client.get(reverse(f"reception:{nome}")).status_code, 200, nome)
        self.assertContains(self.client.get(reverse("reception:cruscotto")), "Mario Esempio")
        self.assertContains(self.client.get(reverse("reception:visita_scheda", args=[v.pk])), "Correggi")
        self.assertContains(self.client.get(reverse("reception:cartellini"), {"stampa": 1}), "data:image/png")

    def test_ingresso_manuale_e_uscita(self):
        r = self.client.post(reverse("reception:registra"), {"nome": "Anna", "cognome": "Prova", "referente": self.ref.pk, "motivo": "Altro", "cartellino": "02"})
        self.assertRedirects(r, reverse("reception:cruscotto"))
        v = Visita.objects.get()
        self.assertEqual((v.cartellino, v.creata_da), ("02", "PANNELLO"))
        self.client.post(reverse("reception:visita_uscita", args=[v.pk]))
        v.refresh_from_db()
        self.assertEqual(v.stato, Visita.USCITO)
        self.assertEqual(EventoVisita.objects.get().azione, "USCITA_FORZATA")

    def test_uscita_solo_post(self):
        v = self.entra()
        self.assertEqual(self.client.get(reverse("reception:visita_uscita", args=[v.pk])).status_code, 405)

    def test_correzione_dalla_scheda(self):
        v = self.entra(quando=timezone.localtime() - timedelta(hours=3))
        quando = timezone.localtime() - timedelta(hours=1)
        self.client.post(reverse("reception:visita_scheda", args=[v.pk]), {"azione": "uscita", "data": f"{quando:%Y-%m-%d}", "ora": f"{quando:%H:%M}"})
        v.refresh_from_db()
        self.assertEqual(v.stato, Visita.USCITO)

    def test_preregistrazione_crea_e_invia(self):
        with patch("reception.mail.invia_invito") as invia:
            self.client.post(reverse("reception:preregistrazioni"), {"nome": "Anna Prova", "email": "a@example.local", "referente": self.ref.pk})
        p = Preregistrazione.objects.get()
        self.assertEqual(len(p.codice), 8)
        invia.assert_called_once()

    def test_mail_che_non_parte_lascia_il_codice(self):
        with patch("reception.mail.invia_invito", side_effect=OSError):
            r = self.client.post(reverse("reception:preregistrazioni"), {"nome": "Anna Prova", "email": "a@example.local", "referente": self.ref.pk}, follow=True)
        self.assertContains(r, "la mail non è partita")
        self.assertTrue(Preregistrazione.objects.exists())

    def test_referenti_e_ditte(self):
        self.client.post(reverse("reception:referenti"), {"nome": "Nuovo", "cognome": "Prova", "email": "n@example.local"})
        self.assertTrue(Referente.objects.filter(email="n@example.local").exists())
        r = self.client.post(reverse("reception:referenti"), {"nome": "Doppio", "cognome": "Prova", "email": "N@example.local"}, follow=True)
        self.assertContains(r, "già di un altro")
        self.client.post(reverse("reception:ditte"), {"nome": "Ditta Nuova"})
        d = DittaAccreditata.objects.get()
        self.client.post(reverse("reception:ditte"), {"azione": "contatto", "pk": d.pk, "nome": "A", "cognome": "B"})
        self.assertEqual(d.contatti.count(), 1)

    def test_cartellini_aggiunti_in_sequenza(self):
        self.client.post(reverse("reception:cartellini"), {"quanti": 2})
        self.assertEqual(list(Cartellino.objects.values_list("numero", flat=True)), ["01", "02", "03", "04"])

    def test_interruttore_avviso(self):
        from core.models import SiteConfig

        self.client.post(reverse("reception:impostazioni"), {"azione": "avviso", "avviso": "1"})
        self.assertEqual(SiteConfig.get("chiosco_avviso_requisiti"), "1")


class ImportazioneTests(TestCase):
    TABELLE = {
        "SELECT * FROM Guests": [{"GuestID": 40, "FirstName": "Mario", "LastName": "Esempio", "Email": "M@example.local", "Phone": None, "Company": "Ditta",
                                  "ConsentDate": datetime(2026, 3, 1, 8), "ConsentIP": "10.0.0.5", "IsAnonymized": 0}],
        "SELECT * FROM Employees": [{"EmployeeID": 3, "FirstName": "Prova", "LastName": "Ref", "Email": "r@example.local", "Department": None, "Phone": None, "IsActive": 1}],
        "SELECT * FROM VisitCategories": [{"CategoryID": 1, "Name": "Altro", "IconEmoji": None, "SortOrder": 5, "IsActive": 1}],
        "SELECT * FROM Badges": [{"BadgeID": 1, "BadgeNumber": "01", "IsAvailable": 1, "LastAssigned": None, "LastReturnedAt": None}],
        "SELECT * FROM Suppliers": [{"SupplierID": 8, "CompanyName": "Ditta", "Notes": None, "IsActive": 1}],
        "SELECT * FROM SupplierContacts": [{"ContactID": 9, "SupplierID": 8, "FirstName": "Mario", "LastName": "Esempio", "IsActive": 1}],
        "SELECT * FROM Visits": [{"VisitID": 1308, "GuestID": 40, "BadgeNumber": "01", "HostEmployee": "Ref Prova", "HostEmail": "r@example.local", "Purpose": "Altro",
                                  "CheckInTime": datetime(2026, 3, 1, 8), "CheckOutTime": datetime(2026, 3, 1, 12), "Status": "CHECKEDOUT", "VisitType": "SUPPLIER",
                                  "SupplierID": 8, "ContactID": 9, "CreatedBy": "SUPPLIER", "Notes": None}],
        "SELECT * FROM PreRegistrations": [{"PreRegID": 5, "Code": "ABCD2345", "GuestName": "Anna Prova", "GuestEmail": "a@example.local", "GuestCompany": None, "HostEmployee": "R",
                                            "HostEmail": "r@example.local", "Purpose": None, "CreatedBy": "admin", "ExpiresAt": datetime(2026, 12, 1), "UsedAt": None, "VisitID": None,
                                            "VisitDate": date(2026, 11, 30), "VisitTimeStart": timedelta(hours=9), "VisitTimeEnd": None}],
        "SELECT * FROM AuditLog WHERE TableName = 'Visits' AND RecordID IS NOT NULL": [{"LogID": 2, "RecordID": 1308, "Action": "SET_CHECKOUT", "PerformedBy": "op", "IPAddress": None, "Details": "{}", "PerformedAt": datetime(2026, 3, 1, 13)}],
    }

    def _lancia(self, *argomenti):
        uscita = StringIO()
        with patch.object(gp, "_esegui", side_effect=lambda sql, params: self.TABELLE[sql]), \
                override_settings(GUESTPORTAL_DB_HOST="h", GUESTPORTAL_DB_USER="u"):
            call_command("importa_guestportal", *argomenti, stdout=uscita)
        return uscita.getvalue()

    def test_la_prova_non_scrive(self):
        testo = self._lancia()
        self.assertFalse(Visita.objects.exists())
        self.assertNotIn("Mario", testo)
        self.assertIn('"nuove": 1', testo)

    def test_apply_tiene_gli_id_e_si_puo_rilanciare(self):
        self._lancia("--apply")
        v = Visita.objects.get()
        self.assertEqual((v.pk, v.ospite_id, v.ditta_id, v.mail_stato), (1308, 40, 8, Visita.MAIL_INVIATA))
        self.assertIsNotNone(v.ingresso.tzinfo)
        self.assertEqual(Preregistrazione.objects.get().ora_inizio, time(9, 0))
        self.assertIn('"da_aggiornare": 1', self._lancia("--apply"))
        self.assertEqual(Visita.objects.count(), 1)

    def test_senza_configurazione_si_ferma(self):
        from django.core.management.base import CommandError

        with override_settings(GUESTPORTAL_DB_HOST="", GUESTPORTAL_DB_USER=""), self.assertRaises(CommandError):
            call_command("importa_guestportal", stdout=StringIO())


class UscitiDimenticatiTests(Base):
    @override_settings(RECEPTION_NATIVA=True)
    def test_avvisa_solo_chi_e_configurato(self):
        self.entra()
        with patch.object(fornitori_tasks, "_destinatari", return_value=[7]) as dest, patch("core.notifiche.invia_notifica") as invia:
            esito = fornitori_tasks.avvisa_usciti_dimenticati()
        self.assertEqual(esito["dentro"], 1)
        self.assertEqual(dest.call_args.args[0], fornitori_tasks.CHIAVE_RUOLI_USCITI)
        self.assertIn("Mario Esempio", invia.call_args.kwargs["messaggio"])

    @override_settings(RECEPTION_NATIVA=True)
    def test_nessuno_dentro_nessun_avviso(self):
        with patch.object(fornitori_tasks, "_destinatari", return_value=[7]), patch("core.notifiche.invia_notifica") as invia:
            fornitori_tasks.avvisa_usciti_dimenticati()
        invia.assert_not_called()


class LettureDiretteTests(Base):
    def test_ditte_vuote(self):
        self.assertEqual(letture.ditte(), [])
