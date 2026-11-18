"""Tessere del Registro accessi cliccabili: la destinazione conta lo stesso insieme. Dati sintetici."""
from __future__ import annotations

import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AttivitaRaccolta, EventoRegistro, FonteLog, Impostazioni, SigilloGiorno


class RegistroKpiLinkTests(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.tmp = Path(tempfile.mkdtemp(prefix="reglog-kpi-"))
        imp = Impostazioni.corrente()
        imp.cartella_archivio = str(self.tmp)
        imp.save()
        admin = get_user_model().objects.create_user("kpi.soc", password="pass-di-prova-123", is_staff=True, is_superuser=True)
        UserOnboarding.objects.update_or_create(user=admin, defaults={"completed": True})
        self.client.force_login(admin)
        self.fonte = FonteLog.objects.create(nome="DC01", tipo=FonteLog.TIPO_WINDOWS, ruolo="dc", host="DC01")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_archivio_tessere_filtrano_i_giorni(self):
        base = date(2026, 9, 1)
        for i, (ok, copia) in enumerate([(True, True), (False, False), (None, False)]):
            SigilloGiorno.objects.create(giorno=base + timedelta(days=i), hash_precedente="0" * 64, hash_sigillo="1" * 64,
                                         verifica_ok=ok, copia_il=timezone.now() if copia else None)
        url = reverse("security:registro_log_archivio")
        r = self.client.get(url)
        tot = r.context["totali"]
        self.assertContains(r, f'href="{url}?giorni=non_integri#giorni"')
        self.assertContains(r, f'href="{url}?giorni=da_copiare#giorni"')
        self.assertEqual(self.client.get(url, {"giorni": "non_integri"}).context["sigilli"].paginator.count, tot["non_integri"])
        self.assertEqual(self.client.get(url, {"giorni": "da_copiare"}).context["sigilli"].paginator.count, tot["da_copiare"])
        self.assertEqual(r.context["sigilli"].paginator.count, tot["giorni"])
        self.assertEqual((tot["non_integri"], tot["da_copiare"]), (1, 2))

    def test_attivita_tessere_filtrano_le_attivita(self):
        for tipo, esito, righe in (("lettura", "ok", 10), ("pc", "ok", 5), ("pc", "errore", 0), ("avvio", "ok", 0)):
            AttivitaRaccolta.objects.create(tipo=tipo, esito=esito, righe=righe)
        url = reverse("security:registro_log_attivita")
        r = self.client.get(url, {"vista": "raccolta", "giorni": "1"})
        rie = r.context["riepilogo"]
        self.assertEqual((rie["letture"], rie["righe"], rie["errori"], rie["avvii"]), (3, 15, 1, 1))
        self.assertContains(r, f'href="{url}?vista=raccolta&amp;giorni=1&amp;tipo=letture#attivita"')
        letture = self.client.get(url, {"vista": "raccolta", "giorni": "1", "tipo": "letture"}).context["pagina"]
        self.assertEqual(letture.paginator.count, rie["letture"])
        self.assertEqual(sum(a.righe for a in letture.object_list), rie["righe"])
        self.assertEqual(self.client.get(url, {"vista": "raccolta", "giorni": "1", "esito": "errore"})
                         .context["pagina"].paginator.count, rie["errori"])
        self.assertEqual(self.client.get(url, {"vista": "raccolta", "giorni": "1", "tipo": "avvio"})
                         .context["pagina"].paginator.count, rie["avvii"])

    def test_persona_falliti_porta_al_catalogo_con_lo_stesso_numero(self):
        ora = timezone.now()
        for i in range(12):  # più di 10 sistemi: la tessera conta tutti, non solo i 10 dell'elenco laterale
            EventoRegistro.objects.create(quando=ora, categoria="accesso", esito="ok", account="mrossi", host=f"PC{i:02d}",
                                          ip_origine=f"10.0.0.{i + 1}", descrizione="Accesso al dominio", fonte_id=self.fonte.pk)
        EventoRegistro.objects.create(quando=ora, categoria="accesso_fallito", esito="ko", account="ESEMPIO\\mrossi",
                                      host="DC01", descrizione="Accesso non riuscito", fonte_id=self.fonte.pk)
        url = reverse("security:registro_log_persona")
        r = self.client.get(url, {"q": "mrossi"})
        kpi = r.context["kpi"]
        self.assertEqual(kpi["usati"], 12)
        self.assertEqual(len(r.context["laterale"]), 10)
        eventi = reverse("security:registro_log_eventi")
        self.assertContains(r, f'href="{eventi}?giorni=7&amp;sezione=falliti&amp;silenziati=1&amp;righe=tutte&amp;chi=mrossi"')
        dest = self.client.get(eventi, {"giorni": "7", "sezione": "falliti", "silenziati": "1", "righe": "tutte", "chi": "mrossi"})
        self.assertEqual(dest.context["totale"], kpi["falliti"])
        self.assertEqual(kpi["falliti"], 1)

    def test_manutenzione_tessere_portano_alle_sezioni(self):
        r = self.client.get(reverse("security:registro_log_manutenzione"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'href="#rl-database"')
        self.assertContains(r, 'id="rl-database"')
        self.assertContains(r, 'id="rl-archivio-mesi"')
