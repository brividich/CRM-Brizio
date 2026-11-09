"""Banco consegne: coda del magazzino per persona, consegna multipla con una firma,
consegna senza richiesta, richieste in attesa del responsabile, chi consegna per categoria (scarpe escluse)."""

from __future__ import annotations

import base64
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from . import flusso, magazzino
from datetime import date, timedelta

from django.utils import timezone

from .models import (
    CategoriaDPI,
    OrdineNegozioDPI,
    TagliaDPI,
    ConsegnaDPI,
    DPIImpostazioni,
    ModelloDPI,
    MovimentoMagazzinoDPI,
    RichiestaDPI,
    StatoRichiesta,
    TipoDPI,
)

User = get_user_model()

_PNG = "data:image/png;base64," + base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16).decode()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class BancoConsegneTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="dpi-banco", password="x", email="b@y.z")
        self.client.force_login(self.admin)
        self.guanti = CategoriaDPI.objects.create(nome="Mani", icona_emoji="gloves", vita_utile_giorni=30)
        self.scarpe = CategoriaDPI.objects.create(nome="Calzature", icona_emoji="boots", consegna_magazzino=False)
        self.mod_guanti = ModelloDPI.objects.create(
            tipo=TipoDPI.objects.create(categoria=self.guanti, nome="Guanti"), codice="GT-1", nome="Blade Safe"
        )
        self.mod_scarpe = ModelloDPI.objects.create(
            tipo=TipoDPI.objects.create(categoria=self.scarpe, nome="S3"), codice="SC-1", nome="Scarpa S3"
        )
        self.url = reverse("dpi:banco")
        patcher = mock.patch("dpi.pdf.render_modulo_consegna_dpi", return_value=b"%PDF")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _richiesta(self, modello, nome="Mario Rossi", legacy=101, quantita=1):
        return RichiestaDPI.objects.create(
            categoria=modello.tipo.categoria, tipo_dpi=modello.tipo, modello_dpi=modello, quantita=quantita,
            stato=StatoRichiesta.APPROVATA, richiedente_nome=nome, richiedente_legacy_id=legacy,
        )

    def test_banco_raggruppa_per_persona_e_esclude_le_scarpe(self):
        self._richiesta(self.mod_guanti)
        self._richiesta(self.mod_guanti, quantita=2)
        self._richiesta(self.mod_scarpe)
        self._richiesta(self.mod_guanti, nome="Luigi Verdi", legacy=102)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        persone = resp.context["persone"]
        self.assertEqual([p["nome"] for p in persone], ["Luigi Verdi", "Mario Rossi"])
        self.assertEqual(len(persone[1]["righe"]), 2)  # la scarpa resta fuori
        self.assertEqual(resp.context["n_altre"], 1)
        self.assertContains(resp, "Mostra anche gli altri DPI (1")
        tutte = self.client.get(self.url + "?tutte=1")
        self.assertEqual(len(tutte.context["persone"][1]["righe"]), 3)

    def test_azione_dalla_pagina_aperta_torna_solo_la_parte_di_lavoro(self):
        r = self._richiesta(self.mod_guanti)
        altra = self._richiesta(self.mod_guanti, nome="Luigi Verdi", legacy=102)
        resp = self.client.post(
            self.url,
            {"azione": "consegna", "ids": [r.pk], "data_consegna": "2026-11-02", "firmato_ricevuta": "1"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["X-Banco-Apri"], "")
        self.assertNotContains(resp, "<html")
        self.assertNotContains(resp, r.numero)
        self.assertContains(resp, altra.numero)
        r.refresh_from_db()
        self.assertEqual(r.stato, StatoRichiesta.CONSEGNATA)

    def test_pronto_dalla_pagina_aperta_resta_sulla_persona(self):
        r = self._richiesta(self.mod_guanti)
        resp = self.client.post(self.url, {"azione": "pronta", "ids": [r.pk]}, headers={"X-Requested-With": "XMLHttpRequest"})
        self.assertEqual(resp["X-Banco-Apri"], "p101")
        self.assertContains(resp, r.numero)

    def test_diretta_dalla_pagina_aperta_apre_la_persona(self):
        self.guanti.consegna_diretta = True
        self.guanti.save()
        with mock.patch("dpi.views._dipendenti_selezionabili", return_value=[{"id": 101, "nome": "Mario Rossi"}]):
            resp = self.client.post(self.url, {
                "azione": "diretta", "dipendente": "101", "modello_dpi_id": self.mod_guanti.pk, "quantita": "1",
            }, headers={"X-Requested-With": "XMLHttpRequest"})
        self.assertEqual(resp["X-Banco-Apri"], "p101")

    def test_azione_senza_javascript_resta_un_redirect(self):
        r = self._richiesta(self.mod_guanti)
        resp = self.client.post(self.url, {"azione": "pronta", "ids": [r.pk]})
        self.assertEqual(resp.status_code, 302)

    def test_aggiornamento_periodico_senza_pagina_intera(self):
        r = self._richiesta(self.mod_guanti)
        resp = self.client.get(self.url, headers={"X-Requested-With": "XMLHttpRequest"})
        self.assertContains(resp, r.numero)
        self.assertNotContains(resp, "<html")

    def test_cambia_modello_al_banco_con_traccia(self):
        altro = ModelloDPI.objects.create(tipo=self.mod_guanti.tipo, codice="GT-2", nome="Altro")
        taglia = TagliaDPI.objects.create(modello=altro, valore="9")
        r = self._richiesta(self.mod_guanti)
        self.client.post(self.url, {"azione": "cambia", "cambia_richiesta": r.pk, "cambia_modello": altro.pk, "cambia_taglia": taglia.pk})
        r.refresh_from_db()
        self.assertEqual((r.modello_dpi_id, r.taglia_dpi_id), (altro.pk, taglia.pk))
        self.assertEqual(r.stato, StatoRichiesta.APPROVATA)
        self.assertIn("Cambiato al banco", r.commenti.get().testo)

    def test_cambia_rifiuta_altra_categoria_taglia_altrui_e_scarpe_ordinate(self):
        r = self._richiesta(self.mod_guanti)
        altro = ModelloDPI.objects.create(tipo=self.mod_guanti.tipo, codice="GT-2", nome="Altro")
        taglia = TagliaDPI.objects.create(modello=self.mod_guanti, valore="8")
        self.client.post(self.url, {"azione": "cambia", "cambia_richiesta": r.pk, "cambia_modello": self.mod_scarpe.pk})
        self.client.post(self.url, {"azione": "cambia", "cambia_richiesta": r.pk, "cambia_modello": altro.pk, "cambia_taglia": taglia.pk})
        r.refresh_from_db()
        self.assertEqual(r.modello_dpi_id, self.mod_guanti.pk)
        ordine = OrdineNegozioDPI.objects.create()
        RichiestaDPI.objects.filter(pk=r.pk).update(modalita_negozio="CONVENZIONE", ordine_negozio=ordine)
        self.client.post(self.url, {"azione": "cambia", "cambia_richiesta": r.pk, "cambia_modello": altro.pk})
        r.refresh_from_db()
        self.assertEqual(r.modello_dpi_id, self.mod_guanti.pk)
        self.assertFalse(r.commenti.exists())

    def test_cambia_fuori_perimetro_non_tocca_nulla(self):
        r = self._richiesta(self.mod_guanti)
        altro = ModelloDPI.objects.create(tipo=self.mod_guanti.tipo, codice="GT-2", nome="Altro")
        with mock.patch("dpi.views._banco_queryset", return_value=RichiestaDPI.objects.none()):
            self.client.post(self.url, {"azione": "cambia", "cambia_richiesta": r.pk, "cambia_modello": altro.pk})
        r.refresh_from_db()
        self.assertEqual(r.modello_dpi_id, self.mod_guanti.pk)

    def test_pagina_collega_il_lettore_di_badge(self):
        pagina = self.client.get(self.url)
        self.assertContains(pagina, 'id="lettore-collega"')
        self.assertContains(pagina, "dpi/js/lettore_badge.js")

    # I messaggi del lettore: 02 + cifre + 03 + XOR + 0D
    @staticmethod
    def _messaggio(cifre, rovina=False):
        dati = bytes([2]) + cifre.encode() + bytes([3])
        controllo = 0
        for b in dati:
            controllo ^= b
        return (dati + bytes([controllo ^ (1 if rovina else 0), 13])).hex()

    def _verifica(self, messaggio):
        return self.client.post(self.url, {"azione": "verifica_badge", "messaggio": messaggio})

    def _consegna(self, richieste, **altro):
        return self.client.post(self.url, {"azione": "consegna", "ids": [r.pk for r in richieste], "data_consegna": "2026-11-06", **altro})

    def _badge(self, legacy=101, numero="42"):
        from anagrafica.models import DipendenteAnagraficaAziendale

        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=legacy, badge=numero)

    def test_verifica_riconosce_la_persona_dal_messaggio_del_lettore(self):
        self._badge()
        risposta = self._verifica(self._messaggio("0000000042")).json()
        self.assertEqual(risposta["esito"], "ok")
        self.assertEqual(risposta["chiave"], "p101")
        self.assertNotIn("42", {str(v) for k, v in risposta.items() if k != "prova"})

    def test_verifica_rifiuta_numero_scritto_a_mano_e_messaggio_rovinato(self):
        self._badge()
        for valore in ("42", "0000000042", self._messaggio("0000000042", rovina=True), "zz"):
            self.assertEqual(self._verifica(valore).json()["esito"], "sconosciuto", valore)

    def test_badge_doppio_non_e_riconosciuto(self):
        self._badge(101, "42")
        self._badge(102, "0042")
        self.assertEqual(self._verifica(self._messaggio("0000000042")).json()["esito"], "sconosciuto")

    def test_troppi_errori_sospendono_la_verifica(self):
        from django.core.cache import cache

        cache.delete(f"dpi_badge_errori:{self.admin.pk}")
        self.addCleanup(cache.delete, f"dpi_badge_errori:{self.admin.pk}")
        for _ in range(20):
            self._verifica("zz")
        self.assertEqual(self._verifica(self._messaggio("0000000042")).status_code, 429)

    def test_conferma_con_badge_vale_come_ricevuta_senza_mail(self):
        from . import report
        from .models import ConfermaConsegnaDPI

        self._badge()
        r = self._richiesta(self.mod_guanti)
        prova = self._verifica(self._messaggio("0000000042")).json()["prova"]
        self._consegna([r], prova_badge=prova)
        c = ConsegnaDPI.objects.get(richiesta=r)
        self.assertIsNotNone(c.confermata_badge_il)
        self.assertEqual(report.ricevuta(c), report.CON_BADGE)
        self.assertFalse(ConfermaConsegnaDPI.objects.exists())

    def test_prova_vale_una_volta_per_la_persona_giusta(self):
        self._badge()
        self._badge(102, "77")
        prova = self._verifica(self._messaggio("0000000042")).json()["prova"]
        altra = self._richiesta(self.mod_guanti, nome="Luigi Verdi", legacy=102)
        self._consegna([altra], prova_badge=prova)
        self.assertFalse(ConsegnaDPI.objects.filter(richiesta=altra).exists())
        r1 = self._richiesta(self.mod_guanti)
        self._consegna([r1], prova_badge=prova)
        self.assertTrue(ConsegnaDPI.objects.filter(richiesta=r1).exists())
        r2 = self._richiesta(self.mod_guanti)
        self._consegna([r2], prova_badge=prova)
        self.assertFalse(ConsegnaDPI.objects.filter(richiesta=r2).exists())

    def test_prova_non_vale_per_un_altro_operatore_ne_scaduta(self):
        from . import badge

        self._badge()
        r = self._richiesta(self.mod_guanti)
        self._consegna([r], prova_badge=badge.crea_prova(self.admin.pk + 1, 101))
        self.assertFalse(ConsegnaDPI.objects.filter(richiesta=r).exists())
        prova = badge.crea_prova(self.admin.pk, 101)
        with mock.patch.object(badge, "DURATA_PROVA_SECONDI", -1):
            self._consegna([r], prova_badge=prova)
        self.assertFalse(ConsegnaDPI.objects.filter(richiesta=r).exists())

    def test_numero_scritto_a_mano_al_posto_della_prova_non_consegna(self):
        self._badge()
        r = self._richiesta(self.mod_guanti)
        self._consegna([r], prova_badge="42")
        self.assertFalse(ConsegnaDPI.objects.filter(richiesta=r).exists())

    def test_conferma_con_mail_per_chi_non_ha_il_badge(self):
        r = self._richiesta(self.mod_guanti)
        with mock.patch("dpi.views._chiedi_conferma") as conferma:
            self.client.post(self.url, {"azione": "consegna", "ids": [r.pk], "data_consegna": "2026-11-06"})
        c = ConsegnaDPI.objects.get(richiesta=r)
        self.assertIsNone(c.confermata_badge_il)
        self.assertFalse(c.firmato_ricevuta)
        conferma.assert_called_once()

    def test_i_numeri_di_badge_non_arrivano_alla_pagina(self):
        self._badge(101, "B-777")
        self._richiesta(self.mod_guanti)
        pagina = self.client.get(self.url)
        self.assertNotContains(pagina, "B-777")
        self.assertContains(pagina, 'data-ha-badge="1"')
        self.assertContains(pagina, "Consegna con badge")
        self.assertContains(pagina, "Consegna con mail")

    def test_lista_di_prelievo_somma_per_modello_e_taglia(self):
        self._richiesta(self.mod_guanti, quantita=2)
        self._richiesta(self.mod_guanti, nome="Luigi Verdi", legacy=102, quantita=3)
        self._richiesta(self.mod_scarpe)
        gia = self._richiesta(self.mod_guanti, nome="Anna Blu", legacy=103)
        RichiestaDPI.objects.filter(pk=gia.pk).update(pronta_ritiro_il=timezone.now())
        magazzino.carica_ddt(self.mod_guanti, 4)
        url = reverse("dpi:banco_prelievo")
        contesto = self.client.get(url).context
        self.assertEqual(len(contesto["gruppi"]), 1)
        g = contesto["gruppi"][0]
        self.assertEqual((g["pezzi"], g["giacenza"], g["manca"]), (5, 4, True))
        self.assertEqual(contesto["n_righe"], 2)
        self.assertEqual(len(self.client.get(url + "?tutte=1").context["gruppi"]), 2)

    def test_lista_di_prelievo_avvisa_solo_gli_spuntati(self):
        a = self._richiesta(self.mod_guanti)
        b = self._richiesta(self.mod_guanti, nome="Luigi Verdi", legacy=102)
        with mock.patch("dpi.views._notifica_richiedente"), mock.patch("dpi.flusso.notifica_pronta_ritiro"):
            self.client.post(reverse("dpi:banco_prelievo"), {"ids": [a.pk]})
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertIsNotNone(a.pronta_ritiro_il)
        self.assertIsNone(b.pronta_ritiro_il)

    def test_bozza_d_ordine_per_ultimo_fornitore(self):
        magazzino.carica_ddt(self.mod_guanti, 1, fornitore="Vecchio", data=date(2026, 1, 1))
        magazzino.carica_ddt(self.mod_guanti, 1, fornitore="Nuovo", data=date(2026, 6, 1))
        self.mod_guanti.scorta_minima = 10
        self.mod_guanti.save()
        altro = ModelloDPI.objects.create(tipo=self.mod_guanti.tipo, codice="GT-2", nome="Altro")
        fornitori = self.client.get(reverse("dpi:magazzino_riordino")).context["fornitori"]
        self.assertEqual([f["nome"] for f in fornitori], ["Nuovo", ""])
        self.assertEqual(fornitori[0]["righe"][0]["modello"].pk, self.mod_guanti.pk)
        self.assertEqual(fornitori[0]["righe"][0]["suggerito"], 18)
        self.assertEqual(fornitori[1]["righe"][0]["modello"].pk, altro.pk)

    def test_strumenti_negati_a_chi_non_gestisce(self):
        with mock.patch("dpi.views._is_gestore", return_value=False):
            self.assertEqual(self.client.get(reverse("dpi:banco_prelievo")).status_code, 302)
            self.assertEqual(self.client.get(reverse("dpi:magazzino_riordino")).status_code, 302)

    def test_giacenza_insufficiente_segnalata(self):
        magazzino.carica_ddt(self.mod_guanti, 1)
        self._richiesta(self.mod_guanti, quantita=3)
        resp = self.client.get(self.url)
        self.assertEqual(resp.context["n_mancanti"], 1)

    def test_consegna_multipla_con_una_firma(self):
        magazzino.carica_ddt(self.mod_guanti, 10)
        a = self._richiesta(self.mod_guanti)
        b = self._richiesta(self.mod_guanti, quantita=2)
        resp = self.client.post(self.url, {
            "azione": "consegna", "ids": [a.pk, b.pk], "data_consegna": "2026-11-02", "firma_immagine": _PNG,
        })
        self.assertEqual(resp.status_code, 302)
        for r in (a, b):
            r.refresh_from_db()
            self.assertEqual(r.stato, StatoRichiesta.CONSEGNATA)
            self.assertEqual(r.consegna.firma_immagine, _PNG)
            self.assertTrue(r.consegna.firmato_ricevuta)
        self.assertEqual(magazzino.giacenza(self.mod_guanti.pk), 7)
        # La seconda consegna dello stesso tipo sostituisce la prima, come dalla scheda.
        self.assertEqual(ConsegnaDPI.objects.filter(sostituita_da__isnull=True).count(), 1)

    def test_consegna_ignora_richieste_non_approvate(self):
        r = self._richiesta(self.mod_guanti)
        r.stato = StatoRichiesta.INVIATA
        r.save()
        self.client.post(self.url, {"azione": "consegna", "ids": [r.pk], "data_consegna": "2026-11-02"})
        r.refresh_from_db()
        self.assertEqual(r.stato, StatoRichiesta.INVIATA)
        self.assertFalse(MovimentoMagazzinoDPI.objects.exists())

    def test_pronto_per_il_ritiro_in_blocco(self):
        a = self._richiesta(self.mod_guanti)
        b = self._richiesta(self.mod_guanti)
        with mock.patch.object(flusso, "notifica_pronta_ritiro") as avviso:
            self.client.post(self.url, {"azione": "pronta", "ids": [a.pk, b.pk]})
            self.client.post(self.url, {"azione": "pronta", "ids": [a.pk]})  # gia' pronta: niente secondo avviso
        self.assertEqual(avviso.call_count, 2)
        a.refresh_from_db()
        self.assertIsNotNone(a.pronta_ritiro_il)

    def test_consegna_senza_richiesta_per_ogni_categoria_tranne_le_scarpe_al_negozio(self):
        self.scarpe.si_ordina_al_negozio = True
        self.scarpe.save()
        with mock.patch("dpi.views._dipendenti_selezionabili", return_value=[{"id": 101, "nome": "Mario Rossi"}]):
            self.client.post(self.url, {"azione": "diretta", "dipendente": 101, "modello_dpi_id": self.mod_scarpe.pk})
            self.assertFalse(RichiestaDPI.objects.exists())  # scarpe: si ordinano al negozio
            resp = self.client.post(self.url, {
                "azione": "diretta", "dipendente": 101, "modello_dpi_id": self.mod_guanti.pk, "quantita": "3",
            })
        r = RichiestaDPI.objects.get()
        self.assertEqual((r.stato, r.quantita, r.richiedente_legacy_id), (StatoRichiesta.APPROVATA, 3, 101))
        self.assertIn("Consegna diretta al banco senza richiesta", r.note_gestione)
        self.assertIn("di norma passa dall'approvazione", r.commenti.get().testo)  # categoria non consumabile: resta scritto
        self.assertTrue(resp["Location"].endswith("#apri-p101"))

    def test_consegna_senza_richiesta_consumabile_lo_dice(self):
        self.guanti.consegna_diretta = True
        self.guanti.save()
        with mock.patch("dpi.views._dipendenti_selezionabili", return_value=[{"id": 101, "nome": "Mario Rossi"}]):
            self.client.post(self.url, {"azione": "diretta", "dipendente": 101, "modello_dpi_id": self.mod_guanti.pk})
        self.assertIn("senza approvazione", RichiestaDPI.objects.get().commenti.get().testo)

    def test_catalogo_della_consegna_senza_richiesta_esclude_le_scarpe_al_negozio(self):
        self.scarpe.si_ordina_al_negozio = True
        self.scarpe.save()
        resp = self.client.get(self.url)
        self.assertTrue(resp.context["ha_diretta"])
        self.assertEqual([m.pk for m in resp.context["modelli_banco"]], [self.mod_guanti.pk])
        self.assertContains(resp, "Consegna senza richiesta")

    def _inviata(self, modello, nome="Mario Rossi", legacy=101):
        r = self._richiesta(modello, nome=nome, legacy=legacy)
        r.stato = StatoRichiesta.INVIATA
        r.save(update_fields=["stato"])
        return r

    def test_richieste_in_attesa_mostrate_nella_scheda_ma_non_spuntabili(self):
        approvata = self._richiesta(self.mod_guanti)
        attesa = self._inviata(self.mod_guanti)
        self._inviata(self.mod_scarpe)  # categoria non del magazzino: solo con «tutte»
        solo_attesa = self._inviata(self.mod_guanti, nome="Luigi Verdi", legacy=102)
        with mock.patch.object(flusso, "approvatori_di", return_value={7}),              mock.patch("dpi.views._nomi_anagrafiche", return_value={7: "Anna Capo"}):
            resp = self.client.get(self.url)
        persone = {p["nome"]: p for p in resp.context["persone"]}
        self.assertEqual(resp.context["n_attesa"], 2)
        self.assertEqual([a["r"].pk for a in persone["Mario Rossi"]["attese"]], [attesa.pk])
        self.assertEqual([riga["r"].pk for riga in persone["Mario Rossi"]["righe"]], [approvata.pk])
        self.assertEqual(persone["Mario Rossi"]["n_attesa"], 1)
        self.assertEqual(persone["Luigi Verdi"]["righe"], [])  # scheda anche con la sola richiesta in attesa
        self.assertEqual([a["r"].pk for a in persone["Luigi Verdi"]["attese"]], [solo_attesa.pk])
        self.assertContains(resp, "in attesa di approvazione di Anna Capo")
        self.assertContains(resp, 'data-attesa="1"')
        self.assertNotContains(resp, f'name="ids" value="{attesa.pk}"')
        tutte = self.client.get(self.url + "?tutte=1")
        self.assertEqual(tutte.context["n_attesa"], 3)

    def test_approva_dal_banco_e_poi_si_consegna(self):
        attesa = self._inviata(self.mod_guanti)
        with mock.patch.object(flusso, "notifica_approvata") as avviso:
            resp = self.client.post(self.url, {"azione": "approva", "approva_richiesta": attesa.pk})
        attesa.refresh_from_db()
        self.assertEqual(attesa.stato, StatoRichiesta.APPROVATA)
        self.assertEqual(avviso.call_count, 1)
        self.assertIn("Approvata al Banco consegne", attesa.commenti.get().testo)
        self.assertTrue(resp["Location"].endswith("#p101"))
        self.client.post(self.url, {"azione": "consegna", "ids": [attesa.pk], "data_consegna": "2026-11-09"})
        attesa.refresh_from_db()
        self.assertEqual(attesa.stato, StatoRichiesta.CONSEGNATA)

    def test_approva_dal_banco_negata_a_chi_non_approva(self):
        attesa = self._inviata(self.mod_guanti)
        with mock.patch("dpi.views._can_approve", return_value=False):
            self.client.post(self.url, {"azione": "approva", "approva_richiesta": attesa.pk})
            resp = self.client.get(self.url)
        attesa.refresh_from_db()
        self.assertEqual(attesa.stato, StatoRichiesta.INVIATA)
        self.assertFalse(resp.context["persone"][0]["attese"][0]["puo_approvare"])
        self.assertNotContains(resp, "data-approva data-richiesta")

    def test_consegna_diretta_dipendente_non_selezionabile(self):
        self.guanti.consegna_diretta = True
        self.guanti.save()
        with mock.patch("dpi.views._dipendenti_selezionabili", return_value=[]):
            self.client.post(self.url, {"azione": "diretta", "dipendente": 999, "modello_dpi_id": self.mod_guanti.pk})
        self.assertFalse(RichiestaDPI.objects.exists())

    def test_banco_negato_a_chi_non_gestisce(self):
        from core.models import UserOnboarding

        utente = User.objects.create_user(username="dpi-op", password="x")
        UserOnboarding.objects.update_or_create(user=utente, defaults={"completed": True})
        self.client.force_login(utente)
        with mock.patch("dpi.views._is_gestore", return_value=False):
            resp = self.client.get(self.url)
            self.client.post(self.url, {"azione": "consegna", "ids": [self._richiesta(self.mod_guanti).pk],
                                        "data_consegna": "2026-11-02"})
        self.assertRedirects(resp, reverse("dpi:dashboard"), fetch_redirect_response=False)
        self.assertFalse(ConsegnaDPI.objects.exists())


class ConsegnaSalvataSubitoTests(TestCase):
    """Dalla pagina aperta la consegna e' subito sul server; mail e PDF aspettano l'annullo."""

    AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

    def setUp(self):
        self.client.force_login(User.objects.create_superuser(username="dpi-subito", password="x", email="s@y.z"))
        self.categoria = CategoriaDPI.objects.create(nome="Mani", icona_emoji="gloves", vita_utile_giorni=30)
        self.tipo = TipoDPI.objects.create(categoria=self.categoria, nome="Guanti")
        self.modello = ModelloDPI.objects.create(tipo=self.tipo, codice="GT-1", nome="Blade Safe")
        self.url = reverse("dpi:banco")
        for bersaglio in ("dpi.pdf.render_modulo_consegna_dpi", "dpi.flusso.notifica_consegnata", "dpi.conferme.richiedi"):
            patcher = mock.patch(bersaglio, return_value=(None, "", 0) if bersaglio.endswith("richiedi") else b"%PDF")
            setattr(self, bersaglio.rpartition(".")[2], patcher.start())
            self.addCleanup(patcher.stop)

    def _richiesta(self, quantita=1):
        return RichiestaDPI.objects.create(
            categoria=self.categoria, tipo_dpi=self.tipo, modello_dpi=self.modello, quantita=quantita,
            stato=StatoRichiesta.APPROVATA, richiedente_nome="Mario Rossi", richiedente_legacy_id=101,
        )

    def _consegna(self, *richieste, **extra):
        dati = {"azione": "consegna", "differisci": "1", "ids": [r.pk for r in richieste], "data_consegna": "2026-11-05"}
        dati.update(extra)
        return self.client.post(self.url, dati, **self.AJAX)

    def test_salvata_subito_senza_avvisi(self):
        magazzino.carica_ddt(self.modello, 5)
        r = self._richiesta()
        resp = self._consegna(r)
        self.assertEqual(resp["X-Banco-Registrate"], str(r.pk))
        r.refresh_from_db()
        self.assertEqual(r.stato, StatoRichiesta.CONSEGNATA)
        self.assertIsNotNone(r.consegna.avvisi_in_sospeso_dal)
        self.assertEqual(magazzino.giacenza(self.modello.pk), 4)
        self.notifica_consegnata.assert_not_called()
        self.richiedi.assert_not_called()

    def test_annulla_torna_da_consegnare_con_traccia(self):
        magazzino.carica_ddt(self.modello, 5)
        r = self._richiesta()
        self._consegna(r)
        resp = self.client.post(self.url, {"azione": "annulla", "ids": [r.pk]}, **self.AJAX)
        self.assertEqual(resp["X-Banco-Annullate"], str(r.pk))
        r.refresh_from_db()
        self.assertEqual(r.stato, StatoRichiesta.APPROVATA)
        self.assertFalse(ConsegnaDPI.objects.filter(richiesta=r).exists())
        self.assertEqual(magazzino.giacenza(self.modello.pk), 5)
        self.assertTrue(r.commenti.filter(testo__contains="annullata").exists())
        self.notifica_consegnata.assert_not_called()
        # Riconsegnata dopo l'annullo, scarica di nuovo.
        self._consegna(r)
        self.assertEqual(magazzino.giacenza(self.modello.pk), 4)

    def test_avvisi_una_volta_sola_poi_non_si_annulla(self):
        magazzino.carica_ddt(self.modello, 5)
        r = self._richiesta()
        self._consegna(r)
        for _ in range(2):
            self.client.post(self.url, {"azione": "avvisi", "ids": [r.pk]}, **self.AJAX)
        self.notifica_consegnata.assert_called_once()
        self.richiedi.assert_called_once()
        r.refresh_from_db()
        self.assertIsNone(r.consegna.avvisi_in_sospeso_dal)
        resp = self.client.post(self.url, {"azione": "annulla", "ids": [r.pk]}, **self.AJAX)
        self.assertEqual(resp["X-Banco-Annullate"], "")
        r.refresh_from_db()
        self.assertEqual(r.stato, StatoRichiesta.CONSEGNATA)

    def test_browser_sparito_gli_avvisi_li_manda_il_task(self):
        from .tasks import run_dpi_avvisi_consegna

        magazzino.carica_ddt(self.modello, 5)
        r = self._richiesta()
        self._consegna(r)
        self.assertEqual(run_dpi_avvisi_consegna()["completate"], 0)  # ancora nel tempo dell'annullo
        ConsegnaDPI.objects.filter(richiesta=r).update(avvisi_in_sospeso_dal=timezone.now() - timedelta(minutes=3))
        self.assertEqual(run_dpi_avvisi_consegna()["completate"], 1)
        self.notifica_consegnata.assert_called_once()
        self.richiedi.assert_called_once()
        self.assertEqual(run_dpi_avvisi_consegna()["completate"], 0)

    def test_senza_differisci_avvisi_immediati(self):
        magazzino.carica_ddt(self.modello, 5)
        r = self._richiesta()
        self.client.post(self.url, {"azione": "consegna", "ids": [r.pk], "data_consegna": "2026-11-05"})
        self.notifica_consegnata.assert_called_once()

    def test_giacenza_insufficiente_chiede_il_motivo(self):
        magazzino.carica_ddt(self.modello, 1)
        r = self._richiesta(quantita=2)
        resp = self._consegna(r)
        self.assertEqual(resp["X-Banco-Motivo"], "1")
        self.assertEqual(resp["X-Banco-Registrate"], "")
        r.refresh_from_db()
        self.assertEqual(r.stato, StatoRichiesta.APPROVATA)
        self.assertEqual(magazzino.giacenza(self.modello.pk), 1)

        self.assertEqual(self._consegna(r, motivo_giacenza="carico non ancora registrato")["X-Banco-Registrate"], str(r.pk))
        movimento = r.movimenti_magazzino.get()
        self.assertIn("carico non ancora registrato", movimento.note)
        self.assertTrue(r.commenti.filter(testo__contains="carico non ancora registrato", is_interno=True).exists())

    def test_giacenza_si_somma_tra_le_richieste_spuntate(self):
        magazzino.carica_ddt(self.modello, 1)
        a, b = self._richiesta(), self._richiesta()
        self.assertEqual(self._consegna(a, b)["X-Banco-Motivo"], "1")

    def test_magazzino_non_in_uso_non_chiede_il_motivo(self):
        r = self._richiesta()
        self.assertEqual(self._consegna(r)["X-Banco-Registrate"], str(r.pk))

    def test_scheda_richiesta_chiede_il_motivo(self):
        magazzino.carica_ddt(self.modello, 1)
        r = self._richiesta(quantita=2)
        self.client.post(reverse("dpi:consegna", args=[r.pk]), {"data_consegna": "2026-11-05", "firmato_ricevuta": "1"})
        r.refresh_from_db()
        self.assertEqual(r.stato, StatoRichiesta.APPROVATA)
        self.assertContains(self.client.get(reverse("dpi:gestione_detail", args=[r.pk])), "Motivo della consegna senza giacenza")
        self.client.post(reverse("dpi:consegna", args=[r.pk]), {
            "data_consegna": "2026-11-05", "firmato_ricevuta": "1", "motivo_giacenza": "rettifica in corso",
        })
        r.refresh_from_db()
        self.assertEqual(r.stato, StatoRichiesta.CONSEGNATA)


class DestinatariConsegnaTests(TestCase):
    def test_scarpe_ai_referenti_il_resto_al_magazzino(self):
        impost = DPIImpostazioni.get_singleton()
        impost.magazzino_emails = "magazzino@example.test"
        impost.notifica_email_extra = "rspp@example.test"
        impost.save()
        guanti = CategoriaDPI.objects.create(nome="Mani")
        scarpe = CategoriaDPI.objects.create(nome="Calzature", consegna_magazzino=False)
        self.assertEqual(flusso.destinatari_consegna(RichiestaDPI(categoria=guanti)), ["magazzino@example.test"])
        self.assertEqual(flusso.destinatari_consegna(RichiestaDPI(categoria=scarpe)), ["rspp@example.test"])


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    SITE_URL="https://hub.example.local", LDAP_ENABLED=False,
)
class MailMagazzinoLinkTests(TestCase):
    def test_avviso_di_consegna_porta_al_banco_sulla_persona(self):
        from django.core import mail

        impost = DPIImpostazioni.get_singleton()
        impost.magazzino_emails = "magazzino@example.test"
        impost.notifica_email_extra = "rspp@example.test"
        impost.save()
        guanti = CategoriaDPI.objects.create(nome="Mani")
        scarpe = CategoriaDPI.objects.create(nome="Calzature", consegna_magazzino=False)
        for cat in (guanti, scarpe):
            flusso.notifica_approvata(RichiestaDPI.objects.create(
                categoria=cat, stato=StatoRichiesta.APPROVATA, richiedente_nome="Mario Rossi", richiedente_legacy_id=101,
            ))
        magazzino_mail, referenti_mail = mail.outbox
        self.assertIn("https://hub.example.local/dpi/banco/#p101", magazzino_mail.body)
        html = magazzino_mail.alternatives[0][0]
        self.assertIn('href="https://hub.example.local/dpi/banco/#p101"', html)
        self.assertIn("Apri il Banco consegne", html)
        self.assertIn("https://hub.example.local/dpi/banco/?tutte=1#p101", referenti_mail.body)

    @override_settings(SITE_URL="")
    def test_senza_indirizzo_del_portale_niente_link(self):
        from django.core import mail

        impost = DPIImpostazioni.get_singleton()
        impost.magazzino_emails = "magazzino@example.test"
        impost.save()
        flusso.notifica_approvata(RichiestaDPI.objects.create(
            categoria=CategoriaDPI.objects.create(nome="Mani"), stato=StatoRichiesta.APPROVATA, richiedente_nome="X",
        ))
        self.assertNotIn("Apri il Banco consegne", mail.outbox[0].body)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class PannelloHomeBancoTests(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.utente = User.objects.create_user(username="dpi-mag", password="x")
        UserOnboarding.objects.update_or_create(user=self.utente, defaults={"completed": True})
        self.client.force_login(self.utente)
        cat = CategoriaDPI.objects.create(nome="Mani")
        self.modello = ModelloDPI.objects.create(tipo=TipoDPI.objects.create(categoria=cat, nome="Guanti"), codice="G", nome="G")
        RichiestaDPI.objects.create(
            categoria=cat, tipo_dpi=self.modello.tipo, modello_dpi=self.modello, quantita=1,
            stato=StatoRichiesta.APPROVATA, richiedente_nome="Mario Rossi", richiedente_legacy_id=101,
        )

    def _home(self, gestore: bool):
        with mock.patch("dpi.views._is_gestore", return_value=gestore):
            return self.client.get(reverse("home_portale:index"))

    def test_chi_gestisce_le_consegne_vede_il_banco_in_home(self):
        resp = self._home(True)
        self.assertEqual(resp.status_code, 200)
        banco = resp.context["banco_dpi"]
        self.assertEqual((banco["n_persone"], banco["n_da_preparare"]), (1, 1))
        self.assertContains(resp, "Banco consegne DPI")
        self.assertContains(resp, reverse("dpi:banco") + "#apri-p101")

    def test_gli_altri_non_lo_vedono_ne_lo_trovano_in_personalizza(self):
        resp = self._home(False)
        self.assertIsNone(resp.context["banco_dpi"])
        self.assertNotIn("banco_dpi", [k for k, _ in resp.context["home_riquadri"]])

    def test_si_puo_nascondere_e_resta_nascosto(self):
        with mock.patch("dpi.views._is_gestore", return_value=True):
            self.client.post(reverse("home_portale:index"), {"azione": "personalizza", "mostra": ["news"]})
        self.assertIsNone(self._home(True).context["banco_dpi"])
        # Chi non lo vede in Personalizza non lo cambia salvando.
        with mock.patch("dpi.views._is_gestore", return_value=False):
            self.client.post(reverse("home_portale:index"), {"azione": "personalizza", "mostra": ["news", "azioni"]})
        self.assertIsNone(self._home(True).context["banco_dpi"])

    def test_ricerca_dalla_home_arriva_nel_banco(self):
        with mock.patch("dpi.views._is_gestore", return_value=True):
            resp = self.client.get(reverse("dpi:banco") + "?cerca=Rossi")
        self.assertContains(resp, 'value="Rossi"')
