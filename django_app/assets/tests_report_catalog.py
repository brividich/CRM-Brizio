"""Catalogo report asset (PROMPT 06 - D). Dati sintetici, IP 192.0.2.x, email example.test."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_tz
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.template import Context, Template
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from contatori.models import LetturaConsumabile, LetturaMensileContatori, Macchina
from core.models import UserOnboarding
from core.test_excel_export import assert_no_live_formula

from .models import Asset, AssetAdministrativeDeadline, AssetFieldHistory, AssetSavedReport
from .services import dashboard_kpi, report_catalog

User = get_user_model()


def _user(username, *, superuser=False, email=""):
    user = User.objects.create_user(username=username, password="x", email=email or f"{username}@example.test",
                                    is_superuser=superuser, is_staff=superuser)
    UserOnboarding.objects.update_or_create(
        user=user, defaults={"completed": True, "skipped": False, "completed_at": timezone.now()})
    return user


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CatalogoTests(TestCase):
    def setUp(self):
        self.admin = _user("rep.admin", superuser=True)
        self.client.force_login(self.admin)
        for i, (reparto, stato) in enumerate([("CED", "IN_USE"), ("CED", "IN_REPAIR"), ("Officina", "IN_USE"),
                                              ("=1+1", "IN_STOCK"), ("", "RETIRED")]):
            Asset.objects.create(asset_tag=f"REP-{i}", name=f"Asset {i}", reparto=reparto, status=stato)

    def test_catalogo_elenca_report_nuovi_ed_esistenti(self):
        body = self.client.get(reverse("assets:report_catalog")).content.decode()
        for d in report_catalog.definizioni().values():
            self.assertIn(reverse("assets:report_catalog_run", args=[d.code]), body)
        self.assertIn("Archivio report programmati", body)

    def test_totali_coerenti_fra_pagina_ed_export(self):
        url = reverse("assets:report_catalog_run", args=["inventario-stato-reparto"])
        response = self.client.get(url)
        risultato = response.context["risultato"]
        self.assertEqual(risultato.totali[-1], Asset.objects.count())
        self.assertEqual(risultato.totali[-1], sum(r[-1] for r in risultato.righe))
        xlsx = self.client.get(url + "?formato=xlsx")
        self.assertEqual(xlsx.status_code, 200)
        wb = assert_no_live_formula(self, xlsx.content)  # reparto "=1+1" resta testo
        ws = wb.active
        valori = [[c.value for c in row] for row in ws.iter_rows()]
        self.assertEqual(valori[-1][-1], risultato.totali[-1])
        testo = " ".join(str(v) for riga in valori for v in riga if v)
        self.assertIn("Estratto il", testo)
        self.assertIn("Filtri:", testo)
        pdf = self.client.get(url + "?formato=pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))

    def test_filtri_applicati(self):
        url = reverse("assets:report_catalog_run", args=["inventario-stato-reparto"])
        risultato = self.client.get(url + "?reparto=CED").context["risultato"]
        self.assertEqual([r[0] for r in risultato.righe], ["CED"])
        self.assertEqual(risultato.totali[-1], 2)
        # Valore non ammesso in una select: ignorato, non passa alla query.
        self.assertEqual(self.client.get(url + "?stato=XXX").status_code, 200)

    def test_report_sconosciuto_404(self):
        self.assertEqual(self.client.get(reverse("assets:report_catalog_run", args=["non-esiste"])).status_code, 404)

    def test_scadenze_e_modifiche(self):
        asset = Asset.objects.get(asset_tag="REP-0")
        AssetAdministrativeDeadline.objects.create(asset=asset, title="Revisione sintetica",
                                                   due_date=timezone.localdate() + timedelta(days=10))
        r = report_catalog.definizioni()["scadenze"].esegui({})
        self.assertEqual(len(r.righe), 1)
        self.assertEqual(r.righe[0][1], "Amministrativa")
        AssetFieldHistory.objects.create(asset=asset, campo="reparto", valore_dopo="CED", fonte="baseline")
        AssetFieldHistory.objects.create(asset=asset, campo="endpoint.ip", valore_prima="192.0.2.1",
                                         valore_dopo="192.0.2.2", fonte="form", autore_display="Sintetico")
        r = report_catalog.definizioni()["modifiche-rete-assegnazioni"].esegui({})
        self.assertEqual(len(r.righe), 1)  # la baseline non e' una modifica
        self.assertEqual(r.righe[0][5:7], ["192.0.2.1", "192.0.2.2"])

    def test_mfc_pagine_nel_periodo(self):
        m = Macchina.objects.create(reparto="Alfa", matricola="SYN-REP-1", host="192.0.2.90")
        for mese, bn in ((date(2026, 7, 1), 1000), (date(2026, 8, 1), 1400), (date(2026, 9, 1), 2000)):
            LetturaMensileContatori.objects.create(macchina=m, mese=mese, a4_bn=bn, a3_bn=0, a4_col=10, a3_col=0)
        LetturaConsumabile.objects.create(macchina=m, nome="Nero", pct=9, rilevata_il=timezone.now())
        r = report_catalog.definizioni()["mfc-pagine-consumabili"].esegui({"dal": "2026-07", "al": "2026-08"})
        riga = r.righe[0]
        self.assertEqual(riga[4:8], [1000, 0, 1000, 0])  # luglio 400 + agosto 600
        self.assertEqual(r.totali[6], 1000)
        self.assertIn("Nero 9%", riga[8])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ReportSalvatiTests(TestCase):
    def setUp(self):
        self.admin = _user("rep.admin2", superuser=True)
        self.user = _user("rep.user")
        self.altro = _user("rep.altro")
        self.code = "inventario-stato-reparto"

    def _salva(self, client_user, **extra):
        self.client.force_login(client_user)
        data = {"nome": "Solo CED", "reparto": "CED", **extra}
        return self.client.post(reverse("assets:report_catalog_save", args=[self.code]), data)

    def test_personale_e_condiviso(self):
        self._salva(self.user)
        salvato = AssetSavedReport.objects.get()
        self.assertEqual(salvato.filtri, {"reparto": "CED"})
        url = reverse("assets:report_catalog_run", args=[self.code]) + f"?salvato={salvato.pk}"
        self.client.force_login(self.altro)
        self.assertEqual(self.client.get(url).status_code, 404)
        salvato.condiviso = True
        salvato.save()
        self.assertEqual(self.client.get(url).status_code, 200)
        # Solo il proprietario elimina.
        self.assertEqual(self.client.post(reverse("assets:report_catalog_delete", args=[salvato.pk])).status_code, 404)
        self.client.force_login(self.user)
        self.client.post(reverse("assets:report_catalog_delete", args=[salvato.pk]))
        self.assertFalse(AssetSavedReport.objects.exists())

    def test_pianificazione_solo_con_permesso(self):
        self._salva(self.user, frequenza="DAILY", destinatari=[self.altro.pk])
        salvato = AssetSavedReport.objects.get()
        self.assertEqual(salvato.frequenza, "")
        self.assertFalse(salvato.destinatari.exists())

    def test_destinatari_senza_accesso_esclusi_e_invio(self):
        senza = self.altro
        with patch("core.middleware.acl_allows_path", side_effect=lambda path, django_user, **kw: django_user != senza):
            self._salva(self.admin, frequenza="DAILY", formato="xlsx", destinatari=[self.user.pk, senza.pk])
            salvato = AssetSavedReport.objects.get()
            self.assertEqual(list(salvato.destinatari.all()), [self.user])
            self.assertIsNotNone(salvato.prossimo_invio)
            salvato.destinatari.add(senza)  # anche se aggiunto dopo, l'invio lo ricontrolla
            ora = salvato.prossimo_invio + timedelta(minutes=1)
            esito = report_catalog.invia_report_pianificati(ora=ora)
        self.assertEqual(esito["inviati"], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to + mail.outbox[0].cc + mail.outbox[0].bcc, [self.user.email])
        self.assertTrue(mail.outbox[0].attachments[0][0].endswith(".xlsx"))
        salvato.refresh_from_db()
        self.assertGreater(salvato.prossimo_invio, ora)
        # Rieseguire subito non rimanda la stessa email.
        self.assertEqual(report_catalog.invia_report_pianificati(ora=ora)["inviati"], 0)

    def test_proprietario_senza_accesso_sospende(self):
        salvato = AssetSavedReport.objects.create(owner=self.user, report_code=self.code, nome="x", frequenza="DAILY",
                                                  prossimo_invio=timezone.now() - timedelta(minutes=1))
        salvato.destinatari.add(self.admin)
        with patch("core.middleware.acl_allows_path", side_effect=lambda path, django_user, **kw: django_user == self.admin):
            report_catalog.invia_report_pianificati()
        salvato.refresh_from_db()
        self.assertEqual(salvato.frequenza, "")
        self.assertEqual(len(mail.outbox), 0)

    def test_proprietario_senza_permesso_di_invio_sospende(self):
        salvato = AssetSavedReport.objects.create(owner=self.admin, report_code=self.code, nome="x", frequenza="DAILY",
                                                  prossimo_invio=timezone.now() - timedelta(minutes=1))
        salvato.destinatari.add(self.user)
        with patch("assets.services.report_catalog.puo_pianificare", return_value=False):
            report_catalog.invia_report_pianificati()
        salvato.refresh_from_db()
        self.assertEqual(salvato.frequenza, "")
        self.assertEqual(len(mail.outbox), 0)

    def test_id_non_numerico_404_e_report_mfc_senza_contatori_403(self):
        self.client.force_login(self.user)
        url = reverse("assets:report_catalog_run", args=[self.code])
        self.assertEqual(self.client.get(url + "?salvato=abc").status_code, 404)
        with patch("assets.services.report_catalog.accesso_extra", return_value=False):
            mfc = self.client.get(reverse("assets:report_catalog_run", args=["mfc-pagine-consumabili"]))
        self.assertEqual(mfc.status_code, 403)

    def test_prossimo_invio(self):
        lunedi = datetime(2026, 10, 12, 8, 0, tzinfo=dt_tz.utc)
        self.assertEqual(timezone.localtime(report_catalog.prossimo_invio("WEEKLY", lunedi)).weekday(), 0)
        self.assertGreater(report_catalog.prossimo_invio("MONTHLY", lunedi), lunedi)
        self.assertIsNone(report_catalog.prossimo_invio(""))


class KpiNonDisponibileTests(TestCase):
    def test_errore_non_diventa_zero_muto(self):
        class _Rotto:
            def count(self):
                raise RuntimeError("db giu'")

            def aggregate(self, **kw):
                raise RuntimeError("db giu'")

        with self.assertLogs("assets.services.dashboard_kpi", level="WARNING"):
            valore = dashboard_kpi._safe_count(_Rotto())
        self.assertEqual(valore + 1, 1)  # resta usabile nei calcoli
        self.assertEqual(str(valore), "dato non disponibile")
        self.assertFalse(dashboard_kpi.kpi_disponibile(valore))
        with self.assertLogs("assets.services.dashboard_kpi", level="WARNING"):
            somma = dashboard_kpi._safe_decimal_sum(_Rotto(), "x")
        html = Template("{% load assets_extras %}{{ v|kpi:1 }}|{{ ok|kpi:0 }}").render(Context({"v": somma, "ok": 3}))
        self.assertEqual(html, "dato non disponibile|3")
