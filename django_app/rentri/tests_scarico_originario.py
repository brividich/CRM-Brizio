"""Segnalazioni 16/11: scarico originale (O) modificabile, FIR sulla O, numero corretto, trasmissione del filo."""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import RegistroRifiuti

User = get_user_model()

CODICE = "12.01.09 * Acqua emulsionata Lt"


def _mov(tipo, giorno, quantita=10, rif_op="", **extra):
    return RegistroRifiuti.objects.create(
        tipo=tipo, data=giorno, codice=extra.pop("codice", CODICE),
        quantita=Decimal(str(quantita)) if quantita is not None else None,
        rif_op=rif_op, unita=extra.pop("unita", "l"), **extra,
    )


def _form(r, **cambi):
    dati = {
        "data": r.data.isoformat(), "codice": r.codice, "unita": r.unita,
        "quantita": "" if r.quantita is None else str(r.quantita),
        "rettifica_scarico": "" if r.rettifica_scarico is None else str(r.rettifica_scarico),
        "rif_op": r.rif_op, "arrivo_fir": r.arrivo_fir, "note_rentri": r.note_rentri,
        "pericolosita": r.pericolosita, "rentri_si_no": r.rentri_si_no,
    }
    dati.update(cambi)
    return dati


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ScaricoOriginarioTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="rentri-o", email="o@example.com", password="x")
        self.client.force_login(self.admin)
        base = timezone.localdate() - timedelta(days=60)
        self.g = lambda n: base + timedelta(days=n)

    def modifica(self, r, **cambi):
        return self.client.post(
            reverse("rentri_modifica", args=[r.pk]), data=json.dumps(_form(r, **cambi)), content_type="application/json",
        )

    def _filo_storico(self, q_o=4000):
        """Forma dello storico: tre carichi, O, R e M che citano i carichi."""
        carichi = [_mov("C", self.g(i), q) for i, q in ((0, 2000), (1, 1000), (2, 1000))]
        rif = ", ".join(c.id_registrazione for c in carichi)
        o = _mov("O", self.g(10), q_o, rif_op=rif, arrivo_fir="GRSLD 000022")
        _mov("R", self.g(11), None, rif_op=rif, rettifica_scarico=Decimal("4620"))
        _mov("M", self.g(12), None, rif_op=rif, rettifica_scarico=Decimal("-4620"), arrivo_fir="GRSLD 000022")
        return carichi, o

    def test_segno_della_o_si_corregge_con_m_nel_filo(self):
        # Prima: escludendo la O dal conto, la M diventava un'uscita e bloccava il salvataggio.
        _, o = self._filo_storico(q_o=4000)
        r = self.modifica(o, quantita="-4000")
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.quantita, Decimal("-4000"))

    def test_quantita_della_o_si_corregge(self):
        _, o = self._filo_storico(q_o=-10)
        r = self.modifica(o, quantita="-4000")
        self.assertEqual(r.status_code, 200, r.content)

    def test_oltre_i_carichi_collegati_suggerisce_gli_altri(self):
        c1 = _mov("C", self.g(0), 10)
        c2 = _mov("C", self.g(1), 1000)
        o = _mov("O", self.g(2), -10, rif_op=c1.id_registrazione)
        r = self.modifica(o, quantita="-1010")
        self.assertEqual(r.status_code, 400)
        self.assertIn(c2.id_registrazione, r.json()["error"])
        r = self.modifica(o, quantita="-1010", rif_op=f"{c1.id_registrazione}, {c2.id_registrazione}")
        self.assertEqual(r.status_code, 200, r.content)

    def test_fir_sulla_o(self):
        c = _mov("C", self.g(0), 100)
        o = _mov("O", self.g(1), -100, rif_op=c.id_registrazione)
        pagina = self.client.get(reverse("rentri_modifica", args=[o.pk]))
        self.assertContains(pagina, 'id="f-arrivo-fir"')
        self.assertContains(pagina, "Numero FIR")
        r = self.modifica(o, arrivo_fir="FIR ABC 000123")
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.arrivo_fir, "FIR ABC 000123")

    def test_numero_si_corregge_su_bozza(self):
        anno = self.g(0).year
        c = _mov("C", self.g(0), 100, id_registrazione=f"{anno}/1847")
        o = _mov("O", self.g(1), -100, rif_op=c.id_registrazione, id_registrazione=f"{anno}/1847")
        r = self.modifica(o, id_registrazione=f"{anno}/1874")
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.id_registrazione, f"{anno}/1874")
        c.refresh_from_db()
        self.assertEqual(c.id_registrazione, f"{anno}/1847")

    def test_numero_aggiorna_i_figli_se_era_unico(self):
        anno = self.g(0).year
        c = _mov("C", self.g(0), 100, id_registrazione=f"{anno}/9001")
        o = _mov("O", self.g(1), -100, rif_op=c.id_registrazione)
        r = self.modifica(c, id_registrazione=f"{anno}/0777")
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.rif_op, f"{anno}/0777")

    def test_numero_rifiutato(self):
        anno = self.g(0).year
        altro = _mov("C", self.g(0), 100)
        o = _mov("O", self.g(1), -50, rif_op=altro.id_registrazione)
        for numero, atteso in (
            (altro.id_registrazione, "già usato"),
            ("1874", "anno/progressivo"),
            (f"{anno - 1}/1874", "anno della data"),
        ):
            with self.subTest(numero=numero):
                r = self.modifica(o, id_registrazione=numero)
                self.assertEqual(r.status_code, 400)
                self.assertIn(atteso, r.json()["error"])
        # Figlio consolidato: il numero del genitore non cambia.
        c = _mov("C", self.g(0), 100, id_registrazione=f"{anno}/9101")
        _mov("O", self.g(2), -100, rif_op=c.id_registrazione, salva=True)
        r = self.modifica(c, id_registrazione=f"{anno}/0778")
        self.assertEqual(r.status_code, 400)
        self.assertIn("consolidate", r.json()["error"])

    def test_trasmetti_filo(self):
        carichi, o = self._filo_storico(q_o=-4000)
        membri = RegistroRifiuti.objects.exclude(pk=o.pk)
        membri.update(salva=True)
        pagina = self.client.get(reverse("rentri_trasmetti_filo", args=[o.pk]))
        self.assertContains(pagina, "Da segnare come trasmesse (5)")
        self.assertContains(pagina, "Restano fuori: bozze (1)")
        r = self.client.post(reverse("rentri_trasmetti_filo", args=[o.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(RegistroRifiuti.objects.filter(rentri_si_no=True).count(), 5)
        o.refresh_from_db()
        self.assertFalse(o.rentri_si_no)
        elenco = self.client.get(reverse("rentri_elenco"))
        self.assertEqual(elenco.status_code, 200)
