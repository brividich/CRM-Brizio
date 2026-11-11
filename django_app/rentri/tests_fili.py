"""Filo conduttore: codice per sei cifre, candidati, collegamento facoltativo, traccia, elenco."""
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

STORICO = "12.01.01 Sfridi Ferro Kg"


def _mov(tipo, giorno, codice=STORICO, quantita=10, rif_op="", **extra):
    return RegistroRifiuti.objects.create(
        tipo=tipo, data=giorno, codice=codice,
        quantita=Decimal(str(quantita)) if quantita is not None else None,
        rif_op=rif_op, unita=extra.pop("unita", "kg"), **extra,
    )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class FiloTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="rentri-filo", email="filo@example.com", password="x")
        self.client.force_login(self.admin)
        self.oggi = timezone.localdate()
        self.ieri = self.oggi - timedelta(days=1)

    def post_json(self, url, payload):
        return self.client.post(url, data=json.dumps(payload), content_type="application/json")

    def candidati(self, tipo, codice, **extra):
        r = self.client.get(reverse("rentri_api_candidati_rif_op"), {"tipo": tipo, "codice": codice, **extra})
        return r.json()["candidati"]

    def test_codice_scritto_diverso_trova_i_carichi(self):
        c = _mov("C", self.ieri - timedelta(days=3), quantita=1000)
        for scritto in ("12 01 01", "120101", "12.01.01"):
            with self.subTest(scritto=scritto):
                cand = self.candidati("O", scritto)
                self.assertEqual([x["id_registrazione"] for x in cand], [c.id_registrazione])
                self.assertEqual(cand[0]["residuo"], 1000.0)
        # Scarico salvato con il codice del catalogo: collegato al carico dello storico.
        r = self.post_json(reverse("rentri_scarico_originale"), {
            "data": self.ieri.isoformat(), "codice": "12 01 01", "quantita": "-1000", "unita": "kg",
            "rif_op": c.id_registrazione,
        })
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.candidati("O", "12 01 01"), [])

    def test_m_e_r_mostrano_il_carico(self):
        c = _mov("C", self.ieri - timedelta(days=10), quantita=3200)
        o = _mov("O", self.ieri - timedelta(days=9), quantita=-3200, rif_op=c.id_registrazione, arrivo_fir="FIR 0001")
        cand = self.candidati("M", "12 01 01")
        self.assertEqual(len(cand), 1)
        self.assertEqual(cand[0]["id_registrazione"], o.id_registrazione)
        self.assertEqual(cand[0]["carichi"], [c.id_registrazione])
        self.assertEqual(cand[0]["stato"], "attesa_m")
        self.assertEqual(self.candidati("R", "12 01 01"), [])
        m = _mov("M", self.ieri, quantita=None, rettifica_scarico=Decimal("-5420"), rif_op=o.id_registrazione)
        self.assertEqual(self.candidati("M", "12 01 01"), [])
        cand_r = self.candidati("R", "12 01 01")
        self.assertEqual([x["id_registrazione"] for x in cand_r], [m.id_registrazione])
        # «Mostra anche i già collegati».
        tutti = self.candidati("M", "12 01 01", tutti="1")
        self.assertEqual([x["id_registrazione"] for x in tutti], [o.id_registrazione])
        self.assertTrue(tutti[0]["gia_collegato"])

    def test_storico_m_r_sul_carico_chiude_il_filo(self):
        # Forma dello storico: M e R citano direttamente il carico.
        c = _mov("C", self.ieri - timedelta(days=10), quantita=2000)
        _mov("O", self.ieri - timedelta(days=9), quantita=-2000, rif_op=c.id_registrazione)
        _mov("M", self.ieri, quantita=None, rettifica_scarico=Decimal("-1060"), rif_op=c.id_registrazione)
        _mov("R", self.ieri, quantita=None, rettifica_scarico=Decimal("1060"), rif_op=c.id_registrazione)
        self.assertEqual(self.candidati("M", STORICO), [])
        self.assertEqual(self.candidati("R", STORICO), [])
        from .giacenze import giacenza_di

        self.assertEqual(giacenza_di(STORICO), Decimal(0))

    def test_collegamento_facoltativo_e_consolidabile(self):
        _mov("C", self.ieri - timedelta(days=3), quantita=100)
        r = self.post_json(reverse("rentri_scarico_originale"), {
            "data": self.ieri.isoformat(), "codice": "12 01 01", "quantita": "-40", "unita": "kg",
        })
        self.assertEqual(r.status_code, 200, r.content)
        o = RegistroRifiuti.objects.get(tipo="O")
        self.client.post(reverse("rentri_consolida", args=[o.pk]))
        o.refresh_from_db()
        self.assertTrue(o.salva)
        # Non collegato: consuma i carichi del codice dal più vecchio.
        from .giacenze import giacenza_di

        self.assertEqual(giacenza_di("12 01 01"), Decimal("60"))
        from .verifica import verifica_registro

        senza = next(s for s in verifica_registro() if s["key"] == "senza_collegamento")["righe"]
        self.assertEqual([x["pk"] for x in senza], [o.pk])

    def test_collegamento_tolto_resta_traccia(self):
        c1 = _mov("C", self.ieri - timedelta(days=5), quantita=10)
        c2 = _mov("C", self.ieri - timedelta(days=4), quantita=10)
        o = _mov("O", self.ieri, quantita=-10, rif_op=c1.id_registrazione)
        r = self.post_json(reverse("rentri_modifica", args=[o.pk]), {
            "data": self.ieri.isoformat(), "codice": STORICO, "quantita": "-10", "unita": "kg",
            "rif_op": c2.id_registrazione,
        })
        self.assertEqual(r.status_code, 200, r.content)
        o.refresh_from_db()
        self.assertEqual(o.rif_op, c2.id_registrazione)
        self.assertIn(c1.id_registrazione, o.rif_op_storico)
        r = self.client.get(reverse("rentri_dettaglio", args=[o.pk]))
        self.assertContains(r, "Collegamenti tolti (traccia)")

    def test_elenco_chiuse_per_codice_e_filtri(self):
        c = _mov("C", self.ieri - timedelta(days=10), quantita=10)
        o = _mov("O", self.ieri - timedelta(days=9), quantita=-10, rif_op=c.id_registrazione)
        _mov("M", self.ieri, quantita=None, rettifica_scarico=Decimal("-12"), rif_op=o.id_registrazione)
        aperto = _mov("C", self.ieri, codice="15 01 06", quantita=5)
        r = self.client.get(reverse("rentri_elenco"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Fili chiusi, per codice")
        self.assertContains(r, "IN DEPOSITO")
        self.assertEqual(len(r.context["gruppi_chiuse"]), 1)
        self.assertEqual(r.context["gruppi_chiuse"][0]["key"], "120101")
        # Filtro per codice (sei cifre) e per stato del filo.
        r = self.client.get(reverse("rentri_elenco"), {"cer": "150106"})
        self.assertEqual([f["id_ancora"] for f in r.context["families"]], [aperto.id_registrazione])
        r = self.client.get(reverse("rentri_elenco"), {"stato": "deposito"})
        self.assertEqual([f["id_ancora"] for f in r.context["families"]], [aperto.id_registrazione])
        r = self.client.get(reverse("rentri_elenco"), {"q": o.id_registrazione, "view": "lista"})
        self.assertContains(r, o.id_registrazione)
        r = self.client.get(reverse("rentri_export_pdf"), {"cer": "150106"})
        self.assertEqual(r.status_code, 200)

    def test_export_excel_filtrato_e_completo(self):
        from io import BytesIO

        from openpyxl import load_workbook

        c = _mov("C", self.ieri - timedelta(days=10), quantita=10)
        _mov("O", self.ieri - timedelta(days=9), quantita=-10, rif_op=c.id_registrazione)
        aperto = _mov("C", self.ieri, codice="15 01 06", quantita=5)
        tolto = _mov("C", self.ieri, codice="15 01 06", quantita=3, annullato=True)

        def righe(params):
            r = self.client.get(reverse("rentri_export_excel"), params)
            self.assertEqual(r.status_code, 200)
            ws = load_workbook(BytesIO(r.content)).active
            valori = [[cl.value for cl in row] for row in ws.iter_rows()]
            testata = next(i for i, v in enumerate(valori) if v[:2] == ["Data", "N. registrazione"])
            return valori[testata], valori[testata + 1:]

        testata, dati = righe({"cer": "150106"})
        self.assertEqual([d[1] for d in dati], [aperto.id_registrazione])
        self.assertEqual(dati[0][testata.index("Stato del filo")], "In deposito")
        # Stato del filo come nell'elenco.
        _t, dati = righe({"stato": "attesa_m"})
        self.assertEqual({d[1] for d in dati}, {c.id_registrazione, RegistroRifiuti.objects.get(tipo="O").id_registrazione})
        # Completo: tutto il registro, annullati compresi.
        _t, dati = righe({"scope": "tutto", "cer": "150106"})
        self.assertEqual(len(dati), 4)
        self.assertIn(tolto.id_registrazione, [d[1] for d in dati])
        r = self.client.get(reverse("rentri_export_pdf"), {"scope": "tutto"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(self.client.get(reverse("rentri_elenco")), "Esporta il registro")


class RicercaCodiceTests(TestCase):
    """«12.01.01» trova il codice per le cifre e non «12.01.09» (segnalazione 11/11)."""

    def setUp(self):
        self.admin = User.objects.create_superuser(username="rentri-cerca", email="cerca@example.com", password="x")
        self.client.force_login(self.admin)
        giorno = timezone.localdate() - timedelta(days=3)
        self.ferro = _mov("C", giorno, codice="12.01.01 Sfridi Ferro Kg", quantita=10)
        self.ferro2 = _mov("C", giorno, codice="12 01 01", quantita=5)
        self.acqua = _mov("C", giorno, codice="12.01.09 * Acqua emulsionata Lt", quantita=7)
        self.batterie = _mov("C", giorno, codice="16.06.02 * Batterie nichel Kg", quantita=1)

    def test_cifre_cer(self):
        from .views import cifre_cer

        self.assertEqual(cifre_cer("12.01.01"), "120101")
        self.assertEqual(cifre_cer("12 01"), "1201")
        self.assertEqual(cifre_cer("120101"), "120101")
        self.assertEqual(cifre_cer("16 06 02*"), "160602")
        self.assertEqual(cifre_cer("2025/1862"), "")
        self.assertEqual(cifre_cer("ferro"), "")
        self.assertEqual(cifre_cer("1234567"), "")

    def _ids(self, q, **extra):
        r = self.client.get(reverse("rentri_elenco"), {"q": q, **extra})
        return {rec.id_registrazione for f in r.context["families"] for rec in f["carichi"] + f["operazioni"]}

    def test_elenco_cerca_codice_per_cifre(self):
        attesi = {self.ferro.id_registrazione, self.ferro2.id_registrazione}
        self.assertEqual(self._ids("12.01.01"), attesi)
        self.assertEqual(self._ids("12 01 01"), attesi)
        self.assertEqual(self._ids("1201"), attesi | {self.acqua.id_registrazione})
        self.assertEqual(self._ids("sfridi ferro"), {self.ferro.id_registrazione})
        self.assertEqual(self._ids(self.batterie.id_registrazione), {self.batterie.id_registrazione})

    def test_vista_fili_ricerca_per_filo(self):
        r = self.client.get(reverse("rentri_elenco"))
        self.assertContains(r, 'id="rn-cerca-fili"')
        self.assertContains(r, 'data-fm-table-skip="1"')
        self.assertContains(r, 'data-cer="120101"')


class ScaricoPrimaDelCaricoTests(TestCase):
    """Uno scarico non collegato non consuma carichi registrati dopo la sua data."""

    def test_scarico_vecchio_non_consuma_carico_successivo(self):
        from datetime import date

        from .fili import analizza

        carico = _mov("C", date(2026, 3, 1), quantita=1500)
        storno = _mov("O", date(2025, 8, 8), quantita=2500)
        a = analizza(list(RegistroRifiuti.objects.all()))
        self.assertEqual(a.residuo[carico.pk], Decimal("1500"))
        self.assertEqual([(m.pk, q) for m, q, _c in a.eccedenze], [(storno.pk, Decimal("2500"))])

    def test_scarico_successivo_consuma_ancora(self):
        from datetime import date

        from .fili import analizza

        carico = _mov("C", date(2026, 3, 1), quantita=1500)
        _mov("O", date(2026, 3, 5), quantita=500)
        a = analizza(list(RegistroRifiuti.objects.all()))
        self.assertEqual(a.residuo[carico.pk], Decimal("1000"))
