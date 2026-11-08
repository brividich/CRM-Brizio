"""Cruscotto dell'elenco e storyline della scheda del Diario preposto."""
from __future__ import annotations

import shutil
import tempfile
from datetime import date, datetime, timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .cruscotto import attivita_recenti, calcola_cruscotto
from .models import SegnalazioneAllegato, SegnalazionePreposto
from .storyline import costruisci_storyline

OGGI = date(2026, 11, 8)


def _dt(d: date, hour=9):
    return timezone.make_aware(datetime(d.year, d.month, d.day, hour, 0), timezone.get_current_timezone())


def _crea(titolo, giorni_fa, preposto="Rossi", registrata_dopo=0, **extra):
    s = SegnalazionePreposto.objects.create(
        titolo=titolo, data_segnalazione=_dt(OGGI - timedelta(days=giorni_fa)),
        descrizione="x", preposto=preposto, chi_segnala=preposto, **extra,
    )
    if registrata_dopo:
        SegnalazionePreposto.objects.filter(pk=s.pk).update(
            created_at=_dt(OGGI - timedelta(days=giorni_fa - registrata_dopo), hour=10))
        s.refresh_from_db()
    return s


class CruscottoTests(TestCase):
    def test_numeri_e_andamento(self):
        # created_at = adesso: per i fatti vecchi conta come registrazione in ritardo.
        _crea("oggi", 0)
        _crea("tre giorni fa", 3, preposto="Bianchi")
        _crea("venti giorni fa", 20)
        _crea("quaranta giorni fa", 40)
        _crea("due anni fa", 700)
        con_allegato = _crea("con allegato", 1)
        SegnalazioneAllegato.objects.create(segnalazione=con_allegato, nome_file="a.txt", file="x/a.txt")
        rimosso = _crea("allegato rimosso", 2)
        SegnalazioneAllegato.objects.create(segnalazione=rimosso, nome_file="b.txt", file="x/b.txt",
                                            rimosso_il=timezone.now())

        c = calcola_cruscotto(SegnalazionePreposto.objects.attive(), oggi=OGGI)

        self.assertEqual(c["totale"], 7)
        self.assertEqual(c["ultimi_7"], 4)          # oggi, 1, 2, 3 giorni fa
        self.assertEqual(c["ultimi_30"], 5)
        self.assertEqual(c["precedenti_30"], 1)
        self.assertEqual(c["delta_30"], 4)
        self.assertEqual(c["senza_allegati"], 6)    # l'allegato rimosso non conta
        self.assertEqual(len(c["andamento"]), 12)
        self.assertEqual(c["andamento"][-1]["etichetta"], "nov")
        self.assertEqual(c["andamento_totale"], 6)  # quella di due anni fa resta fuori
        self.assertEqual(sum(b["valore"] for b in c["giorni_settimana"]), 6)
        self.assertEqual(c["preposti"][0]["etichetta"], "Rossi")
        self.assertEqual(c["preposti"][0]["percento"], 100)

    def test_ritardo_di_registrazione(self):
        _crea("in tempo", 10, registrata_dopo=1)
        _crea("in ritardo", 10, registrata_dopo=5)
        c = calcola_cruscotto(SegnalazionePreposto.objects.filter(titolo__in=["in tempo", "in ritardo"]), oggi=OGGI)
        self.assertEqual(c["in_ritardo"], 1)

    def test_queryset_vuoto(self):
        c = calcola_cruscotto(SegnalazionePreposto.objects.none(), oggi=OGGI)
        self.assertEqual(c["totale"], 0)
        self.assertTrue(all(b["percento"] == 0 for b in c["andamento"]))
        self.assertEqual(c["preposti"], [])

    def test_attivita_recenti_solo_segnalazioni_visibili(self):
        from core.models import AuditLog

        mia = _crea("mia", 1)
        altrui = _crea("altrui", 1)
        AuditLog.objects.all().delete()
        for s in (mia, altrui):
            AuditLog.objects.create(azione="allegato_aggiunto", modulo="diario_preposto", dettaglio={},
                                    oggetto_tipo="diario_preposto.segnalazionepreposto", oggetto_id=str(s.pk))
        voci = attivita_recenti({mia.pk})
        self.assertEqual([v["pk"] for v in voci], [mia.pk])
        self.assertEqual(voci[0]["etichetta"], "Allegato aggiunto")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class VisteTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="dp-vista-")
        self._override = override_settings(DIARIO_PREPOSTO_PRIVATE_ROOT=self._tmp)
        self._override.enable()
        self.admin = get_user_model().objects.create_superuser(username="dp-vista", email="v@example.com", password="x")
        UserOnboarding.objects.create(user=self.admin, completed=True, completed_at=timezone.now())
        self.client.force_login(self.admin)
        self.segnalazione = SegnalazionePreposto.objects.create(
            titolo="Scala senza parapetto", data_segnalazione=timezone.now() - timedelta(days=1),
            descrizione="Magazzino", preposto="Verdi", chi_segnala="Verdi", creato_da=self.admin,
        )

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_elenco_mostra_cruscotto(self):
        resp = self.client.get(reverse("diario_preposto:lista"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Andamento ultimi 12 mesi")
        self.assertContains(resp, "Segnalazioni per preposto")
        self.assertContains(resp, "Nessuna ispezione")
        self.assertEqual(resp.context["cruscotto"]["totale"], 1)

    def test_cruscotto_segue_i_filtri(self):
        resp = self.client.get(reverse("diario_preposto:lista") + "?preposto=Nessuno")
        self.assertEqual(resp.context["cruscotto"]["totale"], 0)
        self.assertTrue(resp.context["cruscotto"]["filtrato"])

    def test_elenco_eliminate_senza_cruscotto(self):
        resp = self.client.get(reverse("diario_preposto:lista") + "?eliminate=1")
        self.assertIsNone(resp.context["cruscotto"])

    def test_storyline_eventi_in_ordine(self):
        from automazioni.models import EmailInviata

        allegato = SegnalazioneAllegato.objects.create(
            segnalazione=self.segnalazione, nome_file="foto.txt",
            file=SimpleUploadedFile("foto.txt", b"x"), sha256="a" * 64, caricato_da=self.admin,
        )
        allegato.rimosso_il = timezone.now()
        allegato.rimosso_da = self.admin
        allegato.save()
        EmailInviata.objects.create(origine="automazione", sorgente="diario_preposto",
                                    record_id=str(self.segnalazione.pk), destinatari="rspp@example.com",
                                    oggetto="Nuova segnalazione", esito=EmailInviata.ESITO_ERRORE, errore="SMTP giù")

        story = costruisci_storyline(self.segnalazione)
        tipi = [e.tipo for e in story["eventi"]]
        self.assertEqual(tipi[0], "fatto")
        self.assertIn("registrata", tipi)
        self.assertIn("allegato", tipi)
        self.assertIn("allegato_rimosso", tipi)
        mail = next(e for e in story["eventi"] if e.tipo == "mail")
        self.assertEqual(mail.stato, "critico")
        self.assertEqual(story["riepilogo"]["mail_ko"], 1)
        self.assertEqual(story["riepilogo"]["allegati"], 0)
        self.assertEqual(story["riepilogo"]["allegati_rimossi"], 1)
        quando = [e.quando for e in story["eventi"]]
        self.assertEqual(quando, sorted(quando))

    def test_storyline_eliminazione_e_ripristino(self):
        self.client.post(reverse("diario_preposto:elimina", args=[self.segnalazione.pk]), {"motivo": "Doppione"})
        self.client.post(reverse("diario_preposto:ripristina", args=[self.segnalazione.pk]))
        self.segnalazione.refresh_from_db()
        tipi = [e.tipo for e in costruisci_storyline(self.segnalazione)["eventi"]]
        self.assertIn("eliminata", tipi)
        self.assertIn("ripristinata", tipi)
        self.assertLess(tipi.index("eliminata"), tipi.index("ripristinata"))

    def test_scheda_mostra_storia_e_sintesi(self):
        resp = self.client.get(reverse("diario_preposto:dettaglio", args=[self.segnalazione.pk]))
        self.assertContains(resp, "Storia della segnalazione")
        self.assertContains(resp, "giorni per registrarla")
        self.assertContains(resp, "Fatto segnalato")
        self.assertContains(resp, "Situazione della segnalazione")
        self.assertContains(resp, "Il preposto: Verdi")

    def test_infografica_percorso_e_controlli(self):
        from automazioni.models import EmailInviata

        from .scheda import infografica

        EmailInviata.objects.create(origine="automazione", sorgente="diario_preposto",
                                    record_id=str(self.segnalazione.pk), destinatari="rspp@example.com",
                                    oggetto="Nuova segnalazione", esito=EmailInviata.ESITO_ERRORE, errore="SMTP giù")
        info = infografica(self.segnalazione, costruisci_storyline(self.segnalazione),
                           SegnalazionePreposto.objects.attive())
        tappe = {t["chiave"]: t for t in info["percorso"]}
        self.assertEqual(list(tappe), ["fatto", "registrata", "documentata", "notificata", "oggi"])
        self.assertEqual(tappe["documentata"]["stato"], "avviso")       # nessun allegato
        self.assertEqual(tappe["notificata"]["stato"], "critico")       # mail in errore
        self.assertEqual(tappe["oggi"]["dopo"], "1 giorno dal fatto")
        voci = {v["titolo"]: v["stato"] for v in info["controlli"]["voci"]}
        self.assertEqual(voci["Registrata in tempo"], "ok")
        self.assertEqual(voci["Notifiche partite"], "critico")
        self.assertEqual(voci["Allegati integri"], "assente")
        self.assertEqual(info["controlli"]["critici"], 1)

    def test_infografica_contesto_preposto(self):
        from .scheda import contesto_preposto

        prima = _crea("prima", 40, preposto="Verdi")
        _crea("altro preposto", 5, preposto="Neri")
        dopo = SegnalazionePreposto.objects.create(titolo="dopo", data_segnalazione=timezone.now(),
                                                   descrizione="x", preposto="Verdi")
        ctx = contesto_preposto(SegnalazionePreposto.objects.attive(), self.segnalazione,
                                oggi=timezone.localdate())
        self.assertEqual(ctx["totale"], 3)
        self.assertEqual(ctx["numero"], 2)
        self.assertEqual(ctx["precedente"]["pk"], prima.pk)
        self.assertEqual(ctx["successiva"]["pk"], dopo.pk)
        self.assertEqual(sum(1 for b in ctx["andamento"] if b["questa"]), 1)
        # Fuori dal perimetro visibile non si conta.
        ctx = contesto_preposto(SegnalazionePreposto.objects.exclude(pk=prima.pk), self.segnalazione)
        self.assertEqual(ctx["totale"], 2)
        self.assertIsNone(ctx["precedente"])

    def test_infografica_eliminata(self):
        from .scheda import infografica

        self.client.post(reverse("diario_preposto:elimina", args=[self.segnalazione.pk]), {"motivo": "Doppione"})
        self.segnalazione.refresh_from_db()
        info = infografica(self.segnalazione, costruisci_storyline(self.segnalazione),
                           SegnalazionePreposto.objects.attive())
        self.assertEqual(info["percorso"][-1]["chiave"], "eliminata")
        self.assertEqual(info["percorso"][-1]["nota"], "Doppione")
        self.assertIsNone(info["contesto"]["numero"])
        resp = self.client.get(reverse("diario_preposto:dettaglio", args=[self.segnalazione.pk]))
        self.assertEqual(resp.status_code, 200)
