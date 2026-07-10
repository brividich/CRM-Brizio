"""Test delle viste (matrice Excel + edit cella HTMX + API Gantt)."""
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from assets.models import Asset

from .models import Macchina, Pianificazione


class ViewsTest(TestCase):
    def setUp(self):
        # superuser: bypassa onboarding/ACL e isola il test alla logica della view
        # (il binding ACL canonico per i ruoli reali e' al PASSO 6).
        self.user = get_user_model().objects.create_superuser(
            username="op", password="x", email="op@example.com"
        )
        self.asset = Asset.objects.create(
            asset_tag="CNC-DM3-1", name="DM3 - DMG Mori", asset_type=Asset.TYPE_WORK_MACHINE
        )
        self.m = Macchina.objects.create(asset=self.asset, categoria=Macchina.CAT_5AXIS)
        self.url_excel = reverse("gestione_carichi_macchina:excel")
        self.url_cella = reverse("gestione_carichi_macchina:cella_edit")

    def test_login_required(self):
        self.assertEqual(self.client.get(self.url_excel).status_code, 302)

    def test_excel_page_mostra_macchina(self):
        self.client.force_login(self.user)
        r = self.client.get(self.url_excel)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "CNC-DM3-1")

    def test_cella_form_get(self):
        self.client.force_login(self.user)
        r = self.client.get(self.url_cella, {"macchina": self.m.id, "turno": "giorno", "data": "2026-06-23"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="testo"')

    def test_cella_salva_crea_manuale(self):
        self.client.force_login(self.user)
        r = self.client.post(self.url_cella, {
            "macchina": self.m.id, "turno": "giorno", "data": "2026-06-23",
            "testo": "8 gimbal (33h)", "stato": "pianificata", "fase": "",
        })
        self.assertEqual(r.status_code, 200)
        p = Pianificazione.objects.get(macchina=self.m, data=date(2026, 6, 23))
        self.assertEqual(p.fonte, Pianificazione.FONTE_MANUALE)
        self.assertEqual(p.qta, 8)
        self.assertEqual(p.ore, 33)

    def test_cella_elimina(self):
        self.client.force_login(self.user)
        p = Pianificazione.objects.create(
            macchina=self.m, data=date(2026, 6, 23), turno="giorno",
            testo_originale="x", fonte=Pianificazione.FONTE_MANUALE,
        )
        r = self.client.post(self.url_cella, {
            "macchina": self.m.id, "turno": "giorno", "data": "2026-06-23",
            "pianificazione_id": p.id, "elimina": "1",
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Pianificazione.objects.filter(pk=p.id).exists())

    def test_api_suggerimento_macchina(self):
        from .models import FamigliaPezzo, MacchinaFamigliaAffinita

        self.client.force_login(self.user)
        fam = FamigliaPezzo.objects.create(nome="gimbal")
        MacchinaFamigliaAffinita.objects.create(macchina=self.m, famiglia=fam, occorrenze=7)
        r = self.client.get(
            reverse("gestione_carichi_macchina:api_suggerimento_macchina"),
            {"famiglia": "gimbal"},
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["suggerimenti"][0]["macchina_id"], self.m.id)

    def test_cella_suggerimento_box(self):
        from .models import FamigliaPezzo, MacchinaFamigliaAffinita

        self.client.force_login(self.user)
        fam = FamigliaPezzo.objects.create(nome="gimbal")
        MacchinaFamigliaAffinita.objects.create(macchina=self.m, famiglia=fam, occorrenze=7)
        # Famiglia riconosciuta dal testo della cella -> box con macchina consigliata.
        r = self.client.get(
            reverse("gestione_carichi_macchina:cella_suggerimento"),
            {"testo": "8 gimbal (33h)", "macchina": self.m.id},
        )
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("gcm-sugg", body)
        self.assertIn(self.m.codice, body)  # codice macchina mostrato
        self.assertIn("●", body)            # evidenziata come macchina della cella
        # Testo senza famiglia riconoscibile -> frammento vuoto (nessun box).
        r2 = self.client.get(
            reverse("gestione_carichi_macchina:cella_suggerimento"),
            {"testo": "zzz ignoto", "macchina": self.m.id},
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.content.decode().strip(), "")

    def test_excel_turni_flag_mostra_righe_turno(self):
        self.client.force_login(self.user)
        self.m.ha_secondo_turno = True
        self.m.ha_turno_notte = True
        self.m.save()
        # Default: 1°+2° turno UNITI -> niente sotto-riga "2° turno"; il notturno resta
        # su riga separata (com'era nel foglio) quando la macchina lo ha.
        r0 = self.client.get(self.url_excel).content.decode()
        self.assertNotIn("↳ 2° turno", r0)
        self.assertIn("↳ notturno", r0)
        # Con ?turni=1: sotto-righe esplicite 2° turno e notturno.
        r1 = self.client.get(self.url_excel, {"turni": "1"}).content.decode()
        self.assertIn("↳ 2° turno", r1)
        self.assertIn("↳ notturno", r1)

    def test_reschedule_cascata_non_tocca_altri_turni(self):
        from datetime import date as _d, timedelta as _td

        from .models import Pianificazione

        self.client.force_login(self.user)
        d = _d(2026, 6, 1)
        p1 = Pianificazione.objects.create(macchina=self.m, turno="giorno", data=d)
        p2 = Pianificazione.objects.create(macchina=self.m, turno="giorno", data=d + _td(days=1))
        pn = Pianificazione.objects.create(macchina=self.m, turno="notte", data=d + _td(days=1))
        r = self.client.post(reverse("gestione_carichi_macchina:reschedule"), {
            "pianificazione_id": p1.id, "giorni_delta": 2, "coda": "1",
            "conferma_slittamento": "1",
        })
        self.assertEqual(r.status_code, 200)
        p2.refresh_from_db(); pn.refresh_from_db()
        self.assertEqual(p2.data, d + _td(days=3))   # coda sullo STESSO turno
        self.assertEqual(pn.data, d + _td(days=1))    # turno diverso: NON toccato

    def test_gantt_corsie_per_fascia(self):
        """Con lavori su fasce diverse (1° e 2°) la riga mostra i chip di fascia (bande)."""
        from .models import Pianificazione

        self.client.force_login(self.user)
        self.m.ha_secondo_turno = True
        self.m.save()
        d = date(2026, 6, 29)  # lunedì
        Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", ore=8, testo_originale="A")
        Pianificazione.objects.create(macchina=self.m, data=d, turno="t2", ore=8, testo_originale="B")
        r = self.client.get(
            reverse("gestione_carichi_macchina:gantt"), {"start": "2026-06-29", "giorni": 7}
        ).content.decode()
        self.assertIn("gband", r)     # chip di fascia presenti
        self.assertIn(">1°<", r)
        self.assertIn(">2°<", r)

    def test_gantt_conflitto_cross_fascia(self):
        """1° turno + Entrambi nello stesso giorno = conflitto (le fasce si intersecano)."""
        from .models import Pianificazione

        self.client.force_login(self.user)
        self.m.ha_secondo_turno = True
        self.m.save()
        d = date(2026, 6, 29)
        Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", ore=8, testo_originale="G")
        Pianificazione.objects.create(macchina=self.m, data=d, turno="entrambi", ore=8, testo_originale="E")
        r = self.client.get(
            reverse("gestione_carichi_macchina:gantt"), {"start": "2026-06-29", "giorni": 7}
        ).content.decode()
        self.assertIn("gcfl", r)  # marcatore ⚠ presente solo sulle barre in conflitto

    def test_api_pianificazione_dettaglio(self):
        from datetime import date as _d

        from .models import Pianificazione

        self.client.force_login(self.user)
        p = Pianificazione.objects.create(
            macchina=self.m, turno="giorno", data=_d(2026, 6, 1),
            testo_originale="8 gimbal (33h)", qta=8, stato="pianificata", fase="sgr",
        )
        r = self.client.get(reverse("gestione_carichi_macchina:api_pianificazione_dettaglio", args=[p.id]))
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["p"]["id"], p.id)
        self.assertEqual(d["p"]["qta"], 8)
        self.assertEqual(d["p"]["stato"], "pianificata")
        self.assertEqual(d["p"]["fase"], "sgr")

    @override_settings(OLLAMA_CHAT_ENABLED=False)
    def test_api_spiega_macchina_failsafe(self):
        from .models import FamigliaPezzo, MacchinaFamigliaAffinita

        self.client.force_login(self.user)
        fam = FamigliaPezzo.objects.create(nome="koala")
        MacchinaFamigliaAffinita.objects.create(macchina=self.m, famiglia=fam, occorrenze=3)
        r = self.client.get(
            reverse("gestione_carichi_macchina:api_spiega_macchina"), {"famiglia": "koala"}
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["suggerimenti"][0]["macchina_id"], self.m.id)
        self.assertIsNone(data["spiegazione"])  # AI off nei test -> fail-safe

    def test_carico_settimanale(self):
        from datetime import date as _d

        from .models import Pianificazione
        from .previsioni import carico_settimanale

        lun = _d(2026, 6, 22)
        # 40h su macchina 8h/gg, 5 gg lavorativi -> capacita' 40 -> 100%
        Pianificazione.objects.create(
            macchina=self.m, data=lun, turno="giorno", ore=40,
            testo_originale="x", fonte=Pianificazione.FONTE_IMPORT,
        )
        weeks = carico_settimanale(lun, 2)
        self.assertEqual(len(weeks), 2)
        self.assertGreater(weeks[0]["totale"]["perc"], 0)

    def test_api_pianificazioni(self):
        self.client.force_login(self.user)
        Pianificazione.objects.create(
            macchina=self.m, data=date(2026, 6, 23), turno="giorno",
            testo_originale="8 gimbal", fonte=Pianificazione.FONTE_IMPORT,
        )
        r = self.client.get(reverse("gestione_carichi_macchina:api_pianificazioni"),
                            {"start": "2026-06-22", "giorni": 7})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["items"]), 1)


class TurniCapabilityTest(TestCase):
    """Turni estesi, capability macchina e capacita' per n. turni."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="op2", password="x", email="op2@example.com"
        )
        self.asset = Asset.objects.create(
            asset_tag="CNC-MZ1-1", name="MZ1 - Mazak", asset_type=Asset.TYPE_WORK_MACHINE
        )
        self.m = Macchina.objects.create(asset=self.asset, categoria=Macchina.CAT_4AXIS)

    def test_turni_consentiti_secondo_flag(self):
        # Solo 1° turno senza flag.
        self.assertEqual(self.m.turni_consentiti(), [Pianificazione.TURNO_GIORNO])
        self.m.ha_secondo_turno = True
        self.assertEqual(
            self.m.turni_consentiti(),
            [Pianificazione.TURNO_GIORNO, Pianificazione.TURNO_T2, Pianificazione.TURNO_ENTRAMBI],
        )
        self.m.ha_turno_notte = True
        # Con entrambi i flag compare anche H24.
        self.assertIn(Pianificazione.TURNO_H24, self.m.turni_consentiti())
        self.assertTrue(self.m.puo_turno(Pianificazione.TURNO_NOTTE))
        self.assertEqual(self.m.n_turni_attivi(), 3)

    def test_ore_giorno_per_turno(self):
        self.m.ore_giorno_disponibili = 8
        self.assertEqual(self.m.ore_giorno_per_turno(Pianificazione.TURNO_GIORNO), 8.0)
        self.assertEqual(self.m.ore_giorno_per_turno(Pianificazione.TURNO_ENTRAMBI), 16.0)
        self.assertEqual(self.m.ore_giorno_per_turno(Pianificazione.TURNO_H24), 24.0)

    def test_capacita_per_n_turni(self):
        from datetime import timedelta

        from .saturazione import calcola_saturazione, working_days

        giorni = [date(2026, 6, 22) + timedelta(days=i) for i in range(7)]
        wd = working_days(giorni)
        self.m.ore_giorno_disponibili = 8
        # Solo 1° turno -> 1x.
        res = calcola_saturazione([self.m], [], giorni)
        self.assertEqual(res["per_macchina"][self.m.id]["capacita"], float(8 * wd))
        # +2° turno -> 2x.
        self.m.ha_secondo_turno = True
        res = calcola_saturazione([self.m], [], giorni)
        self.assertEqual(res["per_macchina"][self.m.id]["capacita"], float(8 * wd * 2))
        # +notte -> 3x.
        self.m.ha_turno_notte = True
        res = calcola_saturazione([self.m], [], giorni)
        self.assertEqual(res["per_macchina"][self.m.id]["capacita"], float(8 * wd * 3))

    def test_suggerimenti_coerenti_col_turno(self):
        from .models import FamigliaPezzo, MacchinaFamigliaAffinita
        from .views import _suggerimenti_macchina

        fam = FamigliaPezzo.objects.create(nome="ragni")
        MacchinaFamigliaAffinita.objects.create(macchina=self.m, famiglia=fam, occorrenze=9)
        # Senza turno notte: un suggerimento per turno notturno esclude la macchina.
        self.assertTrue(_suggerimenti_macchina(fam))  # senza vincolo turno compare
        self.assertEqual(_suggerimenti_macchina(fam, turno=Pianificazione.TURNO_NOTTE), [])
        # Abilitando il notturno la macchina ricompare.
        self.m.ha_turno_notte = True
        self.m.save()
        sug = _suggerimenti_macchina(fam, turno=Pianificazione.TURNO_NOTTE)
        self.assertEqual(sug[0]["macchina_id"], self.m.id)

    def test_suggerimenti_cold_start_fallback_su_fase_globale(self):
        """Famiglia MAI lavorata (nessuno storico proprio): con una fase indicata, il
        suggerimento ricade su quali macchine fanno tipicamente quella fase in generale,
        invece di restare vuoto — segnalato con fallback_globale=True."""
        from .models import FamigliaPezzo
        from .views import _suggerimenti_macchina

        altra = FamigliaPezzo.objects.create(nome="sombrero")
        Pianificazione.objects.create(
            macchina=self.m, famiglia=altra, fase="sgr",
            data=date(2026, 6, 22), turno="giorno",
            stato=Pianificazione.STATO_COMPLETATA, fonte=Pianificazione.FONTE_IMPORT,
        )
        nuova = FamigliaPezzo.objects.create(nome="mai-vista")
        # Senza fase: nessuno storico ne' fallback (il fallback è solo per fase).
        self.assertEqual(_suggerimenti_macchina(nuova), [])
        # Con fase "sgr": eredita il segnale generico dalla fase, non dalla famiglia.
        sug = _suggerimenti_macchina(nuova, fase="sgr")
        self.assertTrue(sug)
        self.assertEqual(sug[0]["macchina_id"], self.m.id)
        self.assertTrue(sug[0]["fallback_globale"])


class GestioneLavoriExtraTest(TestCase):
    """Anti-doppione, duplica, config macchina, impostazioni, overlap."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="op3", password="x", email="op3@example.com"
        )
        self.asset = Asset.objects.create(
            asset_tag="CNC-DM5-1", name="DM5 - DMG", asset_type=Asset.TYPE_WORK_MACHINE
        )
        self.m = Macchina.objects.create(asset=self.asset, categoria=Macchina.CAT_TORNI_FRESA)
        self.client.force_login(self.user)

    def test_cella_anti_doppio_inserimento(self):
        url = reverse("gestione_carichi_macchina:cella_edit")
        payload = {"macchina": self.m.id, "turno": "giorno", "data": "2026-06-23",
                   "testo": "8 gimbal (33h)", "stato": "pianificata", "fase": ""}
        self.client.post(url, payload)
        self.client.post(url, payload)  # doppio submit identico
        self.assertEqual(
            Pianificazione.objects.filter(macchina=self.m, data=date(2026, 6, 23)).count(), 1
        )

    def test_pianificazione_duplica(self):
        p = Pianificazione.objects.create(
            macchina=self.m, data=date(2026, 6, 23), turno="giorno",
            testo_originale="5 sombreri", qta=5, ore=20, fase="fin",
            fonte=Pianificazione.FONTE_IMPORT,
        )
        r = self.client.post(
            reverse("gestione_carichi_macchina:pianificazione_duplica", args=[p.id])
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        copie = Pianificazione.objects.filter(
            macchina=self.m, data=date(2026, 6, 23), testo_originale="5 sombreri"
        )
        self.assertEqual(copie.count(), 2)

    def test_macchina_config_aggiorna_flag(self):
        r = self.client.post(reverse("gestione_carichi_macchina:macchina_config"), {
            "macchina": self.m.id, "ha_secondo_turno": "1", "ha_turno_notte": "1", "ore_giorno": "10",
        })
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["n_turni"], 3)
        self.m.refresh_from_db()
        self.assertTrue(self.m.ha_secondo_turno)
        self.assertTrue(self.m.ha_turno_notte)
        self.assertEqual(float(self.m.ore_giorno_disponibili), 10.0)

    def test_impostazioni_page(self):
        r = self.client.get(reverse("gestione_carichi_macchina:impostazioni"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "CNC-DM5-1")
        self.assertContains(r, "Impostazioni macchine")

    def test_api_sovrapposizione(self):
        # Lavoro da 16h (2 giorni a 8h/gg) gia' presente: un nuovo lavoro nel giorno
        # lavorativo successivo, stesso turno, deve risultare sovrapposto.
        Pianificazione.objects.create(
            macchina=self.m, data=date(2026, 6, 22), turno="giorno", ore=16,
            testo_originale="lavoro A", fonte=Pianificazione.FONTE_IMPORT,
        )
        r = self.client.get(reverse("gestione_carichi_macchina:api_sovrapposizione"), {
            "macchina": self.m.id, "turno": "giorno", "data": "2026-06-23", "ore": "8",
        })
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["overlap"])
        # Turno diverso: nessuna sovrapposizione.
        r2 = self.client.get(reverse("gestione_carichi_macchina:api_sovrapposizione"), {
            "macchina": self.m.id, "turno": "notte", "data": "2026-06-23", "ore": "8",
        })
        self.assertFalse(r2.json()["overlap"])


class ConflittiFasceTest(TestCase):
    """Conflitti per intersezione di fasce orarie (cross-turno nello stesso giorno)."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="op4", password="x", email="op4@example.com"
        )
        self.asset = Asset.objects.create(
            asset_tag="CNC-MK1-1", name="MK1 - Mikron", asset_type=Asset.TYPE_WORK_MACHINE
        )
        self.m = Macchina.objects.create(
            asset=self.asset, categoria=Macchina.CAT_5AXIS,
            ha_secondo_turno=True, ha_turno_notte=True,
        )

    def test_fasce_di(self):
        self.assertEqual(Pianificazione.fasce_di("giorno"), {"G"})
        self.assertEqual(Pianificazione.fasce_di("t2"), {"T"})
        self.assertEqual(Pianificazione.fasce_di("entrambi"), {"G", "T"})
        self.assertEqual(Pianificazione.fasce_di("h24"), {"G", "T", "N"})

    def test_layout_bande_entrambi_alto_e_conflitto(self):
        from .views import _layout_bande

        # giorno (G) + entrambi (G+T) sullo stesso giorno: si contendono la fascia G.
        bars = [
            {"turno": "giorno", "start_idx": 0, "span": 1},
            {"turno": "entrambi", "start_idx": 0, "span": 1},
        ]
        nlanes, bande = _layout_bande(bars, 30)
        # 2 bande (1°/2°) e 2 blocchi (i due lavori non condividono la fascia G) -> 4 lane.
        self.assertEqual(len(bande), 2)
        self.assertEqual(nlanes, 4)
        ent = [b for b in bars if b["turno"] == "entrambi"][0]
        self.assertEqual(ent["lanespan"], 2)             # "Entrambi" alto su 2 fasce
        self.assertTrue(all(b.get("conflitto") for b in bars))

    def test_layout_bande_giorno_e_t2_non_confliggono(self):
        from .views import _layout_bande

        bars = [
            {"turno": "giorno", "start_idx": 0, "span": 1},
            {"turno": "t2", "start_idx": 0, "span": 1},
        ]
        _layout_bande(bars, 30)
        self.assertFalse(any(b.get("conflitto") for b in bars))  # fasce disgiunte (G vs T)

    def test_sovrapposizione_cross_fascia(self):
        from .views import _sovrapposizioni

        d = date(2026, 6, 29)
        Pianificazione.objects.create(macchina=self.m, data=d, turno="entrambi", ore=8, testo_originale="E")
        # 1° turno collide con "Entrambi" (condividono G); 2° turno pure (condividono T).
        self.assertTrue(_sovrapposizioni(self.m, "giorno", d, 8))
        self.assertTrue(_sovrapposizioni(self.m, "t2", d, 8))
        # Notturno non collide con "Entrambi" (fasce disgiunte).
        self.assertFalse(_sovrapposizioni(self.m, "notte", d, 8))

    def test_primo_slot_libero(self):
        from .views import _primo_slot_libero

        d = date(2026, 6, 29)
        Pianificazione.objects.create(macchina=self.m, data=d, turno="giorno", ore=8, testo_originale="G")
        # 1° turno occupato: il primo slot libero stesso giorno è un altro turno (es. 2°/notte).
        slot = _primo_slot_libero(self.m, d, 8, "giorno")
        self.assertIsNotNone(slot)
        self.assertNotEqual(slot["turno"], "giorno")

    def test_api_sovrapposizione_suggerimento(self):
        self.client.force_login(self.user)
        d = date(2026, 6, 29)
        Pianificazione.objects.create(macchina=self.m, data=d, turno="entrambi", ore=8, testo_originale="E")
        r = self.client.get(reverse("gestione_carichi_macchina:api_sovrapposizione"), {
            "macchina": self.m.id, "turno": "giorno", "data": "2026-06-29", "ore": "8",
        })
        d2 = r.json()
        self.assertTrue(d2["overlap"])
        self.assertIsNotNone(d2["suggerimento"])
        self.assertIn("label", d2["suggerimento"])

    def test_h24_occupa_anche_la_fascia_notte(self):
        from .views import _layout_bande

        bars = [{"turno": "h24", "start_idx": 0, "span": 1}]
        nlanes, bande = _layout_bande(bars, 30)
        self.assertEqual(len(bande), 3)            # corsie 1°/2°/Notte
        self.assertEqual(bars[0]["lanespan"], 3)   # barra alta su tutte e 3 le corsie


class AuditEAclTest(TestCase):
    """Registro azioni (audit) + gating UI via permesso canonico (can_edit)."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="op5", password="x", email="op5@example.com"
        )
        self.asset = Asset.objects.create(
            asset_tag="CNC-MZ9-1", name="MZ9 - Mazak", asset_type=Asset.TYPE_WORK_MACHINE
        )
        self.m = Macchina.objects.create(asset=self.asset, categoria=Macchina.CAT_4AXIS)

    def test_log_crea_ed_elimina(self):
        from .models import RegistroAzione

        self.client.force_login(self.user)
        url = reverse("gestione_carichi_macchina:cella_edit")
        self.client.post(url, {"macchina": self.m.id, "turno": "giorno", "data": "2026-06-23",
                               "testo": "8 gimbal (33h)", "stato": "pianificata", "fase": ""})
        self.assertTrue(RegistroAzione.objects.filter(azione="crea", macchina=self.m).exists())
        p = Pianificazione.objects.get(macchina=self.m, data=date(2026, 6, 23))
        self.client.post(url, {"macchina": self.m.id, "turno": "giorno", "data": "2026-06-23",
                               "pianificazione_id": p.id, "elimina": "1"})
        self.assertTrue(RegistroAzione.objects.filter(azione="elimina", pianificazione_id=p.id).exists())

    def test_log_config_e_duplica(self):
        from .models import RegistroAzione

        self.client.force_login(self.user)
        self.client.post(reverse("gestione_carichi_macchina:macchina_config"),
                         {"macchina": self.m.id, "ha_secondo_turno": "1"})
        self.assertTrue(RegistroAzione.objects.filter(azione="config", macchina=self.m).exists())
        p = Pianificazione.objects.create(macchina=self.m, data=date(2026, 6, 23), turno="giorno",
                                          testo_originale="x", fonte=Pianificazione.FONTE_IMPORT)
        self.client.post(reverse("gestione_carichi_macchina:pianificazione_duplica", args=[p.id]))
        self.assertTrue(RegistroAzione.objects.filter(azione="duplica").exists())

    def test_registro_page_e_filtro(self):
        from .models import RegistroAzione

        self.client.force_login(self.user)
        RegistroAzione.objects.create(utente=self.user, utente_nome="op5", azione="crea",
                                      macchina=self.m, macchina_cod=self.m.codice, descrizione="prova")
        r = self.client.get(reverse("gestione_carichi_macchina:registro"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Registro azioni")
        self.assertContains(r, self.m.codice)
        r2 = self.client.get(reverse("gestione_carichi_macchina:registro"), {"azione": "elimina"})
        self.assertEqual(r2.status_code, 200)

    def test_can_edit_nasconde_comandi_a_sola_vista(self):
        # superuser: vede "+ Aggiungi lavoro" (can_edit=True).
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse("gestione_carichi_macchina:gantt")), "+ Aggiungi lavoro")
        # utente normale senza permesso edit: comando di scrittura nascosto.
        normale = get_user_model().objects.create_user("vista", "v@example.com", "x")
        self.client.force_login(normale)
        body = self.client.get(reverse("gestione_carichi_macchina:gantt")).content.decode()
        self.assertNotIn("+ Aggiungi lavoro", body)

    def test_puo_modificare_risolve_grant_di_ruolo_legacy(self):
        # Un utente NON-superuser il cui ruolo legacy ha il grant canonico PERM_EDIT
        # deve poter modificare (→ vede "+ Aggiungi lavoro"). Regressione: _puo_modificare
        # ignorava request.legacy_user, così evaluate_permission_code_access non poteva
        # risolvere il grant di ruolo e negava tutto ai non-superuser (caporeparto compreso).
        from types import SimpleNamespace

        from core.models import PermissionDefinition, RolePermissionGrant

        from .acl_bootstrap import PERM_EDIT
        from .views import _puo_modificare

        ruolo_id = 987654  # id "capo reparto" fittizio, fuori dai ruoli admin
        PermissionDefinition.objects.get_or_create(
            code=PERM_EDIT,
            defaults={"module": "gestione_carichi_macchina", "label": "edit",
                      "description": "", "is_active": True},
        )
        RolePermissionGrant.objects.create(
            legacy_role_id=ruolo_id, permission_id=PERM_EDIT, enabled=True,
        )
        utente = get_user_model().objects.create_user("caporep", "c@example.com", "x")
        legacy = SimpleNamespace(id=ruolo_id, ruolo_id=ruolo_id, ruolo="caporeparto")
        request = SimpleNamespace(user=utente, legacy_user=legacy)
        self.assertTrue(_puo_modificare(request))


class FinestraTest(TestCase):
    """Finestra Gantt: buffer 'all'indietro' di default."""

    def test_giorni_lavorativi_indietro(self):
        from .views import _giorni_lavorativi_indietro

        # lunedì 2026-06-29; 2 gg lavorativi prima = giovedì 25 (salta sab/dom)
        self.assertEqual(_giorni_lavorativi_indietro(date(2026, 6, 29), 2), date(2026, 6, 25))

    def test_finestra_default_parte_dal_passato(self):
        from django.test import RequestFactory
        from django.utils import timezone

        from .views import _finestra

        req = RequestFactory().get(reverse("gestione_carichi_macchina:gantt"))
        start, n, giorni = _finestra(req)
        self.assertEqual(giorni[0], start)
        self.assertLess(start, timezone.localdate())  # default: finestra parte PRIMA di oggi

    def test_finestra_start_esplicito_non_bufferato(self):
        from django.test import RequestFactory

        from .views import _finestra

        req = RequestFactory().get(
            reverse("gestione_carichi_macchina:gantt"), {"start": "2026-06-29", "giorni": "7"}
        )
        start, n, giorni = _finestra(req)
        self.assertEqual(start, date(2026, 6, 29))  # start esplicito rispettato
