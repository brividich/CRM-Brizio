"""Segnalazione 21/11: M e O (e M e R) possono avere lo stesso numero, anche correggendolo dopo.

Dati sintetici. Ricalca i casi dei log di utilizzo: M storica che cita il carico
con lo stesso numero della sua O, FIR storico su due righe.
"""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .catena import numero_condivisibile
from .fili import analizza_codice
from .models import RegistroRifiuti
from .tests_scarico_originario import _form, _mov

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class NumeroCondivisoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="rentri-mo", email="mo@example.com", password="x")
        self.client.force_login(self.admin)
        base = timezone.localdate() - timedelta(days=60)
        self.g = lambda n: base + timedelta(days=n)
        self.anno = self.g(0).year

    def modifica(self, r, **cambi):
        return self.client.post(
            reverse("rentri_modifica", args=[r.pk]), data=json.dumps(_form(r, **cambi)), content_type="application/json",
        )

    def _filo(self):
        c = _mov("C", self.g(0), 2500)
        o = _mov("O", self.g(5), -2500, rif_op=c.id_registrazione, id_registrazione=f"{self.anno}/7001")
        m = _mov("M", self.g(6), None, rif_op=c.id_registrazione, rettifica_scarico=Decimal("-2480"))
        return c, o, m

    def test_m_prende_il_numero_della_sua_o(self):
        c, o, m = self._filo()
        r = self.modifica(m, id_registrazione=o.id_registrazione)
        self.assertEqual(r.status_code, 200, r.content)
        m.refresh_from_db()
        self.assertEqual(m.id_registrazione, o.id_registrazione)

    def test_o_prende_il_numero_della_sua_m(self):
        c, o, m = self._filo()
        r = self.modifica(o, id_registrazione=m.id_registrazione)
        self.assertEqual(r.status_code, 200, r.content)

    def test_m_collegata_alla_o_con_lo_stesso_numero(self):
        # Prima: «un movimento non può collegarsi a sé stesso».
        c, o, m = self._filo()
        m.id_registrazione = o.id_registrazione
        m.save(update_fields=["id_registrazione"])
        r = self.modifica(m, rif_op=o.id_registrazione)
        self.assertEqual(r.status_code, 200, r.content)
        # Il filo risale alla O e da lì al carico: la M non diventa un'uscita.
        an = analizza_codice(c.codice)
        self.assertEqual(an.collegati[m.pk], [c.pk])
        self.assertNotIn(m.pk, an.uscita)
        self.assertEqual(an.residuo[c.pk], Decimal(0))
        scheda = self.client.get(reverse("rentri_dettaglio", args=[m.pk]))
        self.assertEqual([g.pk for g in scheda.context["genitori"]], [o.pk])

    def test_numero_condiviso_rifiutato_fuori_dalle_coppie(self):
        c, o, m = self._filo()
        altro_c = _mov("C", self.g(1), 100)
        altra_o = _mov("O", self.g(7), -100, rif_op=altro_c.id_registrazione)
        for registro, numero in (
            (altra_o, o.id_registrazione),            # due O
            (o, c.id_registrazione),                  # O con un carico
            (m, altro_c.id_registrazione),            # M con un carico
        ):
            with self.subTest(tipo=registro.tipo, numero=numero):
                r = self.modifica(registro, id_registrazione=numero)
                self.assertEqual(r.status_code, 400)
                self.assertIn("già usato", r.json()["error"])
        # Stesso tipo di coppia ma CER diverso.
        m_altro_cer = _mov("M", self.g(8), None, rettifica_scarico=Decimal("-5"), codice="15 01 06")
        r = self.modifica(m_altro_cer, id_registrazione=o.id_registrazione)
        self.assertEqual(r.status_code, 400)

    def test_regola(self):
        def r(tipo, codice="12 01 01"):
            return RegistroRifiuti(tipo=tipo, codice=codice)

        self.assertTrue(numero_condivisibile(r("M"), [r("O")]))
        self.assertTrue(numero_condivisibile(r("R"), [r("M")]))
        self.assertTrue(numero_condivisibile(r("R"), [r("M"), r("O")]))
        self.assertFalse(numero_condivisibile(r("R"), [r("O")]))
        self.assertFalse(numero_condivisibile(r("M"), [r("M")]))
        self.assertFalse(numero_condivisibile(r("M"), [r("C")]))
        self.assertFalse(numero_condivisibile(r("M"), [r("O", "15 01 06")]))

    def test_duplicati_om_non_sono_anomalie(self):
        from .numerazione import id_duplicati

        c, o, m = self._filo()
        RegistroRifiuti.objects.filter(pk=m.pk).update(id_registrazione=o.id_registrazione)
        gruppi = {g["id_registrazione"]: g for g in id_duplicati()}
        self.assertTrue(gruppi[o.id_registrazione]["coppia_rm"])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class FirSuDueRigheTests(TestCase):
    """Lo storico ha il FIR su due righe: il modulo incollava le parole («JYSCARICO»)."""

    def setUp(self):
        self.admin = User.objects.create_superuser(username="rentri-fir", email="fir@example.com", password="x")
        self.client.force_login(self.admin)
        self.giorno = timezone.localdate() - timedelta(days=30)

    def test_modulo_mostra_il_fir_su_una_riga_e_salva_con_lo_spazio(self):
        c = _mov("C", self.giorno, 100)
        o = _mov("O", self.giorno, -100, rif_op=c.id_registrazione,
                 arrivo_fir="FIR NR. XXXXX 000001 AB\nSCARICO VERIFICATO", note_rentri="riga uno\nriga due")
        pagina = self.client.get(reverse("rentri_modifica", args=[o.pk]))
        self.assertContains(pagina, 'value="FIR NR. XXXXX 000001 AB SCARICO VERIFICATO"')
        dati = _form(o, arrivo_fir="FIR NR. XXXXX 000001 AB\nSCARICO VERIFICATO", note_rentri="riga uno\r\nriga due")
        r = self.client.post(reverse("rentri_modifica", args=[o.pk]), data=json.dumps(dati),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.arrivo_fir, "FIR NR. XXXXX 000001 AB SCARICO VERIFICATO")
        self.assertEqual(o.note_rentri, "riga uno\nriga due")
