"""Gruppi da Excel (entrano ed escono con il capogruppo) e allegati delle visite. Dati sintetici."""
from __future__ import annotations

import io
import shutil
import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from core.models import UserOnboarding

from . import importa as imp
from . import servizi
from .api_chiosco import _checkin_submit
from .models import AllegatoVisita, Cartellino, CategoriaVisita, PartecipanteGruppo, Preregistrazione, Referente, Visita

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TMP = tempfile.mkdtemp(prefix="pn-rc-allegati-")


def _xlsx(righe, intestazione=("Cognome", "Nome", "Azienda / scuola", "Email", "Telefono")) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["Elenco partecipanti"])  # titolo sopra l'intestazione: va trovata lo stesso
    ws.append(list(intestazione))
    for r in righe:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _file(contenuto: bytes, nome="elenco.xlsx"):
    return SimpleUploadedFile(nome, contenuto, content_type=XLSX)


CLASSE = [("Rossi", "Anna", "Istituto Esempio", "", ""), ("Bianchi", "Luca", "Istituto Esempio", "", "3330000000"),
          ("Verdi", "Sara", "Istituto Esempio", "sara.verdi@example.local", "")]


@override_settings(RECEPTION_NATIVA=True, ANAGRAFICA_PRIVATE_ROOT=TMP)
class Base(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TMP, ignore_errors=True)

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_superuser("rc_admin", "rc.admin@example.local", "x")
        UserOnboarding.objects.get_or_create(user=self.user, defaults={"completed": True})
        self.client.force_login(self.user)
        self.ref = Referente.objects.create(nome="Paola", cognome="Interna", email="paola.interna@example.local")
        CategoriaVisita.objects.create(nome="Visita guidata")
        for n in ("01", "02"):
            Cartellino.objects.create(numero=n)

    def invito(self, **kw):
        dati = dict(ospite_nome="Marco Docente", ospite_email="", referente=self.ref, creata_da="test",
                    motivo="Visita guidata", data_visita=timezone.localdate())
        dati.update(kw)
        return servizi.crea_preregistrazione(**dati)

    def aggiungi(self, pre=None, capo=None, righe=CLASSE, **kw):
        return imp.salva_partecipanti([dict(zip(("cognome", "nome", "azienda", "email", "telefono"), r), n=i + 3)
                                       for i, r in enumerate(righe)], preregistrazione=pre, visita_capo=capo, **kw)


class LetturaTests(Base):
    def test_modello_si_rilegge_e_intestazione_sotto_un_titolo(self):
        wb = load_workbook(io.BytesIO(imp.modello_xlsx()))
        self.assertEqual([c.value for c in wb["Ospiti"][1]], list(imp.COLONNE))
        righe = imp.leggi_xlsx(io.BytesIO(_xlsx(CLASSE + [("", "", "", "", "")])))
        self.assertEqual(len(righe), 3)
        self.assertEqual(righe[1]["telefono"], "3330000000")
        self.assertEqual(righe[0]["n"], 3)

    def test_errori_riga_per_riga(self):
        righe = imp.leggi_xlsx(io.BytesIO(_xlsx([("Rossi", "", "", "", ""), ("Neri", "Ugo", "", "senza-chiocciola", "")])))
        errori = imp.controlla(righe)
        self.assertEqual(len(errori), 2)
        self.assertIn("Riga 3", errori[0])
        with self.assertRaises(imp.ImportNonValido):
            imp.leggi_xlsx(io.BytesIO(_xlsx([("a", "b")], intestazione=("Persona", "Ditta"))))

    def test_email_di_un_altra_persona_ferma_tutto(self):
        servizi.ospite_da_dati(nome="Altro", cognome="Nome", email="sara.verdi@example.local")
        with self.assertRaises(imp.ImportNonValido) as err:
            self.aggiungi(pre=self.invito())
        self.assertIn("Riga 5", err.exception.righe[0])
        self.assertFalse(PartecipanteGruppo.objects.exists())


class GruppoTests(Base):
    def test_entrano_con_il_codice_ed_escono_con_il_capogruppo(self):
        pre = self.invito()
        esito = self.aggiungi(pre=pre)
        self.assertEqual((esito.aggiunti, esito.entrati), (3, 0))
        self.assertFalse(Visita.objects.exists())
        capo = servizi.ingresso_da_codice(pre.codice)
        dentro = Visita.objects.filter(stato=Visita.DENTRO, creata_da="GRUPPO")
        self.assertEqual(dentro.count(), 3)
        self.assertTrue(all(v.cartellino == Visita.SENZA_CARTELLINO for v in dentro))
        self.assertEqual(set(dentro.values_list("referente_email", flat=True)), {self.ref.email})
        self.assertEqual(len(servizi.cartellini_liberi()), 1)  # solo il capogruppo ha il cartellino
        servizi.registra_uscita(capo.pk, origine="PANNELLO")
        self.assertFalse(Visita.objects.filter(stato=Visita.DENTRO).exists())

    def test_capogruppo_al_chiosco_per_nome_usa_l_invito_di_oggi(self):
        pre = self.invito()
        self.aggiungi(pre=pre)
        stato, _ = _checkin_submit({"first_name": "Marco", "last_name": "Docente", "host_employee": self.ref.nome_elenco,
                                    "host_email": self.ref.email, "purpose": "Visita guidata"}, "")
        self.assertEqual(stato, 200)
        pre.refresh_from_db()
        self.assertIsNotNone(pre.usata_il)
        self.assertEqual(Visita.objects.filter(stato=Visita.DENTRO).count(), 4)

    def test_invito_di_un_altro_giorno_non_scatta(self):
        pre = self.invito(data_visita=timezone.localdate() + timedelta(days=3))
        self.aggiungi(pre=pre)
        servizi.registra_ingresso(servizi.ospite_da_dati(nome="Marco", cognome="Docente"), referente_nome="x", invia_mail=False)
        self.assertEqual(Visita.objects.count(), 1)

    def test_chi_e_gia_dentro_con_cartellini_e_doppi_saltati(self):
        capo = servizi.registra_ingresso(servizi.ospite_da_dati(nome="Marco", cognome="Docente"), referente_nome="Interna Paola",
                                         cartellino="", invia_mail=False)
        esito = self.aggiungi(capo=capo, righe=CLASSE[:2], con_cartellini=True)
        self.assertEqual(esito.entrati, 2)
        self.assertEqual(servizi.cartellini_liberi(), [])
        esito = self.aggiungi(capo=capo, righe=CLASSE[:2])
        self.assertEqual((esito.aggiunti, len(esito.doppi)), (0, 2))
        with self.assertRaises(imp.ImportNonValido):  # nessun cartellino libero per il terzo
            self.aggiungi(capo=capo, righe=CLASSE[2:], con_cartellini=True)
        servizi.registra_uscita(capo.pk, origine="PANNELLO")
        self.assertEqual(len(servizi.cartellini_liberi()), 2)

    def test_togli_dal_gruppo_registra_l_uscita(self):
        capo = servizi.registra_ingresso(servizi.ospite_da_dati(nome="Marco", cognome="Docente"), referente_nome="x", cartellino="",
                                         invia_mail=False)
        self.aggiungi(capo=capo, righe=CLASSE[:1])
        p = PartecipanteGruppo.objects.get()
        risposta = self.client.post(reverse("reception:partecipante_togli", args=[p.pk]))
        self.assertRedirects(risposta, reverse("reception:visita_scheda", args=[capo.pk]), fetch_redirect_response=False)
        self.assertEqual(Visita.objects.filter(stato=Visita.DENTRO).count(), 1)


class PaginaImportTests(Base):
    @patch("reception.mail.invia_invito")
    def test_nuovo_invito_dal_modulo(self, invia):
        risposta = self.client.post(reverse("reception:importa"), {
            "destinazione": "nuovo", "file": _file(_xlsx(CLASSE)), "capo_cognome": "Docente", "capo_nome": "Marco",
            "capo_email": "marco.docente@example.local", "referente": self.ref.pk, "giorno": timezone.localdate().isoformat(),
            "motivo": "Visita guidata",
        })
        pre = Preregistrazione.objects.get()
        self.assertRedirects(risposta, reverse("reception:invito_gruppo", args=[pre.pk]), fetch_redirect_response=False)
        self.assertEqual(pre.partecipanti.count(), 3)
        invia.assert_called_once()
        pagina = self.client.get(reverse("reception:invito_gruppo", args=[pre.pk]))
        self.assertContains(pagina, "Bianchi Luca")
        self.assertContains(self.client.get(reverse("reception:cruscotto")), "+3 con lui")

    def test_file_con_errori_non_crea_l_invito(self):
        risposta = self.client.post(reverse("reception:importa"), {
            "destinazione": "nuovo", "file": _file(_xlsx([("Rossi", "", "", "", "")])), "capo_cognome": "Docente",
            "capo_nome": "Marco", "referente": self.ref.pk, "giorno": timezone.localdate().isoformat(),
        })
        self.assertEqual(risposta.status_code, 200)
        self.assertContains(risposta, "Riga 3: mancano cognome o nome.")
        self.assertFalse(Preregistrazione.objects.exists())

    def test_modello_scaricabile(self):
        risposta = self.client.get(reverse("reception:importa_modello"))
        self.assertEqual(risposta["Content-Type"], XLSX)
        self.assertIn("modello_import_ospiti.xlsx", risposta["Content-Disposition"])
        self.assertContains(self.client.get(reverse("reception:importa")), "Scarica il modello Excel")


class AllegatiTests(Base):
    def test_carica_scarica_elimina_e_pulizia(self):
        capo = servizi.registra_ingresso(servizi.ospite_da_dati(nome="Marco", cognome="Docente"), referente_nome="x", cartellino="",
                                         invia_mail=False)
        url = reverse("reception:visita_allegati", args=[capo.pk])
        self.client.post(url, {"file": SimpleUploadedFile("elenco.pdf", b"%PDF-1.4 sintetico", content_type="application/pdf")})
        a = AllegatoVisita.objects.get()
        self.assertEqual(a.nome, "elenco.pdf")
        scarico = self.client.get(reverse("reception:visita_allegato", args=[capo.pk, a.pk]))
        self.assertEqual(b"".join(scarico.streaming_content), b"%PDF-1.4 sintetico")
        self.client.post(url, {"file": SimpleUploadedFile("script.exe", b"MZ")})
        self.assertEqual(AllegatoVisita.objects.count(), 1)
        self.client.post(url, {"file": SimpleUploadedFile("finto.pdf", b"<html><script></script></html>")})
        self.assertEqual(AllegatoVisita.objects.count(), 1)  # contenuto diverso dall'estensione: rifiutato
        self.client.post(url, {"azione": "elimina", "allegato": a.pk})
        self.assertFalse(AllegatoVisita.objects.exists())
        self.assertFalse(a.file.storage.exists(a.file.name))
