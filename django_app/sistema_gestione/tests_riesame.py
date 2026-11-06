"""Verbale di riesame MOD.062. Dati sintetici."""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from scadenzario import fonti_moduli

from .acl_bootstrap import _ROUTE_BINDINGS, PERM_RIESAME_APPROVA, PERM_RIESAME_EDIT, PERM_RIESAME_VIEW
from .exports import riesame_pdf
from .models import Riesame, RiesameObiettivo, RiesamePartecipante
from .services import panoramica
from .services import riesame as S


def _crea(utente, anno=2026, data=date(2026, 3, 10)):
    return S.crea_riesame(Riesame(anno=anno, data=data, periodo_dal=date(anno, 1, 1), periodo_al=data),
                          utente=utente, aree=None)


def _completa(riesame):
    riesame.documenti_esaminati = "Tabelle KPI"
    riesame.save()
    riesame.argomenti.update(analisi="Analisi di prova")
    if not riesame.partecipanti.exists():
        RiesamePartecipante.objects.create(riesame=riesame, funzione="DIG", nome="Persona Prova")


class ServizioTests(TestCase):
    def setUp(self):
        self.u = get_user_model().objects.create_superuser("rz_su", password="x")

    def test_nuovo_verbale_ha_argomenti_e_indicatori(self):
        r = _crea(self.u)
        self.assertEqual(r.argomenti.count(), len(S.ARGOMENTI))
        audit = r.argomenti.get(codice="f")
        self.assertEqual({i["slug"] for i in audit.indicatori}, {"audit-interni", "certificazioni-audit-esterni"})
        self.assertTrue(audit.indicatori[0]["kpi"])
        self.assertEqual(r.argomenti.get(codice="c").indicatori, [])

    def test_indicatori_solo_delle_aree_di_chi_prepara(self):
        r = S.crea_riesame(Riesame(anno=2026, data=date(2026, 3, 10), periodo_dal=date(2026, 1, 1),
                                   periodo_al=date(2026, 3, 10)), utente=self.u, aree={"qualita"})
        self.assertEqual(r.argomenti.get(codice="ISMS").indicatori, [])
        self.assertTrue(r.argomenti.get(codice="f").indicatori)

    def test_proposta_elenca_cosa_manca_e_poi_passa(self):
        r = _crea(self.u)
        with self.assertRaises(S.TransizioneNonAmmessa):
            S.proponi(r)
        self.assertEqual(len(S.problemi_proposta(r)), 3)
        _completa(r)
        S.proponi(r)
        self.assertEqual(r.stato, Riesame.STATO_PROPOSTO)

    def test_obiettivo_senza_responsabile_blocca_la_proposta(self):
        r = _crea(self.u)
        _completa(r)
        RiesameObiettivo.objects.create(riesame=r, descrizione="x")
        self.assertTrue(any("Nuovi obiettivi" in p for p in S.problemi_proposta(r)))

    def _approvato(self, **kw):
        r = _crea(self.u, **kw)
        _completa(r)
        o = RiesameObiettivo.objects.create(riesame=r, descrizione="Ridurre gli scarti", responsabile=self.u,
                                            scadenza=date(2026, 12, 31), risultato_atteso="-10%")
        S.proponi(r)
        S.approva(r, utente=self.u)
        return r, o

    def test_gli_obiettivi_tornano_nel_verbale_dopo_e_la_valutazione_resta_fissata(self):
        _vecchio, o = self._approvato()
        nuovo = _crea(self.u, anno=2027, data=date(2027, 3, 10))
        self.assertEqual(list(S.obiettivi_precedenti(nuovo)), [o])
        _completa(nuovo)
        self.assertTrue(any("livello di raggiungimento" in p for p in S.problemi_proposta(nuovo)))
        S.valuta_precedente(nuovo, o, stato=RiesameObiettivo.STATO_RAGGIUNTO, nota="Fatto")
        self.assertEqual(list(S.obiettivi_precedenti(nuovo)), [o])
        S.proponi(nuovo)
        S.approva(nuovo, utente=self.u)
        self.assertEqual(nuovo.fotografia_precedenti[0]["stato"], "Raggiunto")
        o.nota = "cambiata dopo"
        o.save()
        nuovo.refresh_from_db()
        self.assertEqual(nuovo.fotografia_precedenti[0]["nota"], "Fatto")
        terzo = _crea(self.u, anno=2028, data=date(2028, 3, 10))
        self.assertEqual(list(S.obiettivi_precedenti(terzo)), [])

    def test_in_corso_resta_da_valutare_anche_al_giro_dopo(self):
        _vecchio, o = self._approvato()
        nuovo = _crea(self.u, anno=2027, data=date(2027, 3, 10))
        S.valuta_precedente(nuovo, o, stato=RiesameObiettivo.STATO_APERTO, nota="A metà")
        _completa(nuovo)
        S.proponi(nuovo)
        S.approva(nuovo, utente=self.u)
        terzo = _crea(self.u, anno=2028, data=date(2028, 3, 10))
        self.assertEqual(list(S.obiettivi_precedenti(terzo)), [o])

    def test_ripianificato_crea_una_copia_sola_e_si_toglie_se_si_cambia_idea(self):
        _vecchio, o = self._approvato()
        nuovo = _crea(self.u, anno=2027, data=date(2027, 3, 10))
        for _ in range(2):
            S.valuta_precedente(nuovo, o, stato=RiesameObiettivo.STATO_RIPIANIFICATO, nota="Slitta")
        copia = nuovo.obiettivi.get()
        self.assertEqual((copia.origine, copia.descrizione, copia.scadenza), (o, o.descrizione, None))
        S.valuta_precedente(nuovo, o, stato=RiesameObiettivo.STATO_NON_RAGGIUNTO, nota="No")
        self.assertFalse(nuovo.obiettivi.exists())

    def test_prossimo_riesame_entro_un_anno_anche_dal_29_febbraio(self):
        self.assertIsNone(S.prossimo_riesame())
        self._approvato(anno=2028, data=date(2028, 2, 29))
        self.assertEqual(S.prossimo_riesame(), date(2029, 2, 28))

    def test_da_fare_e_scadenzario(self):
        oggi = timezone.localdate()
        self.assertTrue(any("Nessun verbale" in v["testo"] for v in panoramica.da_fare(oggi, audit=False, riesame=True)))
        _r, o = self._approvato(anno=oggi.year - 1, data=oggi - timedelta(days=400))
        RiesameObiettivo.objects.filter(pk=o.pk).update(scadenza=oggi - timedelta(days=1))
        voci = panoramica.da_fare(oggi, audit=False, riesame=True)
        self.assertEqual(voci[0]["testo"], "Riesame della direzione oltre l'anno")
        self.assertTrue(any("oltre la scadenza" in v["testo"] for v in voci))
        self.assertEqual({i.kind for i in _raccolti()}, {"riesame", "obiettivo_riesame"})

    def test_pdf_in_ogni_stato(self):
        r, _o = self._approvato()
        self.assertTrue(riesame_pdf(r).startswith(b"%PDF"))
        self.assertTrue(riesame_pdf(_crea(self.u, anno=2027, data=date(2027, 1, 1))).startswith(b"%PDF"))


def _raccolti():
    """Le voci del Sistema di gestione come le raccoglie lo Scadenzario per il sistema."""
    from unittest.mock import patch

    def item(_ctx, _source, kind, *_a, **_k):
        return SimpleNamespace(kind=kind)

    ctx = SimpleNamespace(sistema=True, orizzonte=timezone.localdate() + timedelta(days=30))
    with patch.object(fonti_moduli, "_item", side_effect=item):
        return fonti_moduli._sgi_riesame(ctx)


class VisteTests(TestCase):
    def setUp(self):
        self.u = get_user_model().objects.create_superuser("rz_v", password="x")
        self.client.force_login(self.u)
        self.resp = get_user_model().objects.create_user("rz_resp", password="x")

    def test_tutte_le_rotte_hanno_il_permesso_giusto(self):
        from .urls import urlpatterns

        rotte = [f"sistema_gestione:{p.name}" for p in urlpatterns if p.name and p.name.startswith("riesame_")]
        self.assertEqual(len(rotte), 17)
        for rotta in rotte:
            self.assertIn(_ROUTE_BINDINGS[rotta], {PERM_RIESAME_VIEW, PERM_RIESAME_EDIT, PERM_RIESAME_APPROVA}, rotta)
        self.assertEqual(_ROUTE_BINDINGS["sistema_gestione:riesame_approva"], PERM_RIESAME_APPROVA)

    def test_percorso_completo(self):
        r = self.client.post(reverse("sistema_gestione:riesame_nuovo"), {
            "anno": 2026, "data": "2026-03-10", "periodo_dal": "2026-01-01", "periodo_al": "2026-03-10",
            "documenti_esaminati": "Tabelle KPI"})
        riesame = Riesame.objects.get()
        url = reverse("sistema_gestione:riesame_dettaglio", args=[riesame.pk])
        self.assertRedirects(r, url, fetch_redirect_response=False)
        html = self.client.get(url).content.decode()
        self.assertIn("Prima di proporlo", html)
        self.assertNotIn("{#", html)

        self.client.post(reverse("sistema_gestione:riesame_partecipante_aggiungi", args=[riesame.pk]),
                         {"funzione": "DIG", "utente": self.u.pk})
        self.assertEqual(riesame.partecipanti.get().nominativo, "rz_v")
        analisi = {f"analisi_{a.pk}": "Testo" for a in riesame.argomenti.all()}
        self.client.post(reverse("sistema_gestione:riesame_salva_analisi", args=[riesame.pk]), analisi)
        self.client.post(reverse("sistema_gestione:riesame_obiettivo_nuovo", args=[riesame.pk]), {
            "descrizione": "Obiettivo", "responsabile": self.resp.pk, "scadenza": "2026-12-31"})
        self.client.post(reverse("sistema_gestione:riesame_proponi", args=[riesame.pk]))
        riesame.refresh_from_db()
        self.assertEqual(riesame.stato, Riesame.STATO_PROPOSTO)
        self.client.post(reverse("sistema_gestione:riesame_approva", args=[riesame.pk]))
        riesame.refresh_from_db()
        self.assertEqual((riesame.stato, riesame.approvato_da), (Riesame.STATO_APPROVATO, self.u))

        # Approvato: il testo non cambia, l'andamento sì.
        chiave = f"analisi_{riesame.argomenti.first().pk}"
        self.client.post(reverse("sistema_gestione:riesame_salva_analisi", args=[riesame.pk]), {chiave: "Cambiato"})
        self.assertEqual(riesame.argomenti.first().analisi, "Testo")
        o = riesame.obiettivi.get()
        self.client.post(reverse("sistema_gestione:riesame_obiettivo", args=[riesame.pk, o.pk]),
                         {"descrizione": "Altro", "nota": "A buon punto"})
        o.refresh_from_db()
        self.assertEqual((o.descrizione, o.nota), ("Obiettivo", "A buon punto"))
        self.assertEqual(self.client.get(reverse("sistema_gestione:riesame_pdf", args=[riesame.pk])).status_code, 200)
        self.assertContains(self.client.get(reverse("sistema_gestione:riesame_elenco")), "Obiettivo")

    def test_senza_permessi_niente_verbale(self):
        r = _crea(self.u)
        self.client.force_login(self.resp)
        risposta = self.client.get(reverse("sistema_gestione:riesame_dettaglio", args=[r.pk]))
        self.assertIn(risposta.status_code, (302, 403))
        self.client.post(reverse("sistema_gestione:riesame_approva", args=[r.pk]))
        r.refresh_from_db()
        self.assertEqual(r.stato, Riesame.STATO_BOZZA)

    def test_obiettivo_di_altro_verbale_non_si_tocca(self):
        a, b = _crea(self.u), _crea(self.u, anno=2027, data=date(2027, 1, 1))
        o = RiesameObiettivo.objects.create(riesame=a, descrizione="x")
        r = self.client.post(reverse("sistema_gestione:riesame_obiettivo_togli", args=[b.pk, o.pk]))
        self.assertEqual(r.status_code, 404)
        self.assertTrue(RiesameObiettivo.objects.filter(pk=o.pk).exists())
