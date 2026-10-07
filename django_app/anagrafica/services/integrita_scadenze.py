"""Check di integrita' delle scadenze HR: visite, formazione, qualifiche, DPI. SOLA LETTURA.

Ogni controllo produce una :class:`Sezione` con gravita':

- ``errore``: dato sicuramente sbagliato (scade prima di iniziare, data nel futuro,
  persona inesistente, doppioni, cache disallineata dal motore);
- ``avviso``: dato da guardare (configurazione incoerente, override manuali);
- ``info``: comportamento voluto ma utile da vedere (visite anticipate).

Usato da ``manage.py verifica_scadenze_hr`` (anche col profilo ``prod_readonly``).
Non scrive nulla: i rimedi sono indicati in ``Sezione.rimedio``.
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from anagrafica.reportistica.dati import filtra_in

logger = logging.getLogger(__name__)

AREE = ("visite", "formazione", "qualifiche", "dpi")


@dataclass
class Sezione:
    area: str
    titolo: str
    gravita: str  # errore | avviso | info
    righe: list[str] = field(default_factory=list)
    rimedio: str = ""


def _d(data) -> str:
    return f"{data:%d/%m/%Y}" if data else "—"


class _Verifica:
    def __init__(self, legacy_ids=None, oggi: date | None = None):
        from anagrafica.services import requisiti

        self.ctx = requisiti.ambito(oggi)
        self.oggi = self.ctx.today
        self.sezioni: list[Sezione] = []
        self.legacy_ids = legacy_ids
        self.persone = None
        if legacy_ids:
            from anagrafica.services.scadenze import _persone

            self.persone = _persone(self.ctx, legacy_ids)
            self.id_filtro = set(self.ctx.id_estesi(self.persone)) | {int(i) for i in legacy_ids}
        else:
            self.id_filtro = None
        self.esistenti = self._id_esistenti()

    def _id_esistenti(self) -> set[int] | None:
        from django.db import transaction

        try:
            from core.legacy_models import AnagraficaDipendente

            # Savepoint: se la tabella legacy manca, l'errore non rompe la transazione del chiamante.
            with transaction.atomic():
                ids = set(AnagraficaDipendente.objects.values_list("id", flat=True))
            # Anagrafica vuota (DB nuovo, test): non si puo' dire chi non esiste.
            return ids or None
        except Exception:
            logger.warning("integrita scadenze: anagrafica legacy non leggibile", exc_info=True)
            return None

    def _qs(self, qs, campo="legacy_anagrafica_id"):
        return filtra_in(qs, campo, self.id_filtro) if self.id_filtro is not None else list(qs)

    def add(self, area, titolo, gravita, righe, rimedio=""):
        self.sezioni.append(Sezione(area, titolo, gravita, list(righe), rimedio))

    def orfani(self, area, oggetti, desc):
        if self.esistenti is None:
            return
        self.add(area, "Persona inesistente in anagrafica", "errore",
                 [desc(o) for o in oggetti if o.legacy_anagrafica_id not in self.esistenti],
                 "Record di un id anagrafica cancellato o mai esistito (import): ricollegare o eliminare.")

    @staticmethod
    def doppi(oggetti, chiave):
        conta = Counter(chiave(o) for o in oggetti)
        return [k for k, n in conta.items() if n > 1]

    # ── Visite ────────────────────────────────────────────────────────────
    def visite(self):
        from anagrafica.models import TipoVisitaMedica, VisitaMedica, _add_months
        from anagrafica.services import requisiti
        from anagrafica.services.referti_parsing import PERIODICITA_NOTE

        a = "visite"
        cadenze = re.compile(r"\b(" + "|".join(PERIODICITA_NOTE) + r")\b", re.IGNORECASE)
        tipi = list(TipoVisitaMedica.objects.order_by("nome"))
        incoerenti, senza_durata, senza_famiglia = [], [], []
        for t in tipi:
            m = cadenze.search(t.nome or "")
            durata = t.durata_mesi or 0
            if m and durata != PERIODICITA_NOTE[m.group(1).lower()]:
                incoerenti.append(f"tipo #{t.pk} «{t.nome}»: durata {durata} mesi, il nome indica "
                                  f"{PERIODICITA_NOTE[m.group(1).lower()]}")
            if t.is_active and t.obbligatoria and durata <= 0:
                senza_durata.append(f"tipo #{t.pk} «{t.nome}»")
            if t.is_active and m and not (t.categoria or "").strip():
                senza_famiglia.append(t)
        self.add(a, "Tipi con durata diversa dalla cadenza nel nome", "errore", incoerenti,
                 "Correggere la durata in Impostazioni visite.")
        self.add(a, "Tipi obbligatori senza durata (mai in scadenza)", "avviso", senza_durata)
        # Stesso esame con cadenze diverse ma senza famiglia: la visita nuova non
        # supera la vecchia, che resta «scaduta» nello scadenziario.
        radici = defaultdict(list)
        for t in senza_famiglia:
            radici[re.sub(r"\s+", " ", cadenze.sub("", t.nome)).strip(" -()").lower()].append(t)
        self.add(a, "Esami con piu' cadenze senza famiglia (categoria)", "avviso",
                 [", ".join(f"#{t.pk} «{t.nome}»" for t in ts) for ts in radici.values() if len(ts) > 1],
                 "Dare la stessa categoria ai tipi: la visita piu' recente supera le precedenti.")

        visite = self._qs(VisitaMedica.objects.select_related("tipo"))

        def desc(v):
            return f"visita #{v.pk} persona {v.legacy_anagrafica_id} «{v.tipo.nome}» del {_d(v.data_svolgimento)}"

        # Visite correnti contro il motore dei requisiti (ricalcolo prudente).
        persone = self.persone if self.persone is not None else {p.id: p for p in self.ctx.dipendenti()}
        voci = [x for x in requisiti.visite(self.ctx, persone) if x.visita_id] if persone else []
        per_id = {v.pk: v for v in visite}
        divergenti, anticipate = [], []
        for voce in voci:
            v = per_id.get(voce.visita_id)
            if v is None:
                continue
            if v.data_scadenza != voce.scadenza or (v.scadenza_nota or "") != voce.nota[:300]:
                divergenti.append(f"{desc(v)}: salvata {_d(v.data_scadenza)}, attesa {_d(voce.scadenza)}")
            elif voce.nota:
                anticipate.append(f"{desc(v)}: {_d(voce.scadenza_propria)} → {_d(voce.scadenza)} — {voce.nota}")
        self.add(a, "Visite correnti con scadenza diversa dal motore", "errore", divergenti,
                 "manage.py ricalcola_scadenze_hr (gira anche ogni notte).")
        self.add(a, "Visite correnti anticipate dal requisito (corrette)", "info", anticipate)

        mancanti, prima, oltre, futuro = [], [], [], []
        for v in visite:
            durata = v.tipo.durata_mesi or 0
            propria = _add_months(v.data_svolgimento, durata) if durata > 0 else None
            if propria and v.data_scadenza is None:
                mancanti.append(f"{desc(v)}: il tipo prevede {_d(propria)}")
            if v.data_scadenza and v.data_scadenza < v.data_svolgimento:
                prima.append(f"{desc(v)}: scade il {_d(v.data_scadenza)}")
            elif propria and v.data_scadenza and v.data_scadenza > propria:
                oltre.append(f"{desc(v)}: scade il {_d(v.data_scadenza)}, oltre il {_d(propria)} del tipo")
            if v.data_svolgimento > self.oggi:
                futuro.append(desc(v))
        self.add(a, "Visite senza scadenza con tipo a durata", "errore", mancanti)
        self.add(a, "Visite che scadono prima di essere fatte", "errore", prima)
        self.add(a, "Visite con scadenza oltre quella del tipo", "errore", oltre)
        self.add(a, "Visite con data nel futuro", "errore", futuro)
        self.add(a, "Visite doppie (persona, tipo, data)", "errore",
                 [f"persona {k[0]}, tipo #{k[1]}, {_d(k[2])}" for k in
                  self.doppi(visite, lambda v: (v.legacy_anagrafica_id, v.tipo_id, v.data_svolgimento))])
        self.orfani(a, visite, desc)

    # ── Formazione ────────────────────────────────────────────────────────
    def formazione(self):
        from anagrafica.models import _add_months
        from anagrafica.models_formazione import TrainingDeadline, TrainingEmployeeRecord
        from anagrafica.services.training_deadline_service import _compute_stato

        a = "formazione"
        recs = self._qs(TrainingEmployeeRecord.objects.select_related("corso"))

        def desc(r):
            return (f"attestato #{r.pk} persona {r.legacy_anagrafica_id} corso {r.corso.codice} "
                    f"«{r.corso.titolo[:50]}» del {_d(r.data_completamento)}")

        una_tantum_con_scad: dict[int, list] = defaultdict(list)
        senza, prima, futuro = [], [], []
        for r in recs:
            vc = r.corso.validita_mesi or 0
            if vc <= 0 and r.data_scadenza:
                una_tantum_con_scad[r.corso_id].append(r)
            if vc > 0 and r.data_scadenza is None:
                senza.append(f"{desc(r)}: il corso vale {vc} mesi, atteso {_d(_add_months(r.data_completamento, vc))}")
            if r.data_scadenza and r.data_scadenza < r.data_completamento:
                prima.append(f"{desc(r)}: scade il {_d(r.data_scadenza)}")
            if r.data_completamento > self.oggi:
                futuro.append(desc(r) + (f" (sessione #{r.sessione_id})" if r.sessione_id else ""))
        righe = []
        for rs in una_tantum_con_scad.values():
            c = rs[0].corso
            scaduti = sum(1 for r in rs if r.data_scadenza < self.oggi)
            mesi = Counter(round((r.data_scadenza - r.data_completamento).days / 30.44) for r in rs).most_common(1)[0][0]
            righe.append(f"corso {c.codice} «{c.titolo[:60]}»: {len(rs)} attestati con scadenza "
                         f"(~{mesi} mesi, {scaduti} gia' scaduti) ma il corso e' a validita' 0")
        self.add(a, "Corsi «una tantum» con attestati che scadono", "avviso", righe,
                 "Lo stato segue la scadenza dell'attestato; impostare la validita' del corso "
                 "perche' anche i nuovi attestati abbiano la scadenza.")
        self.add(a, "Attestati senza scadenza di corsi con validita'", "avviso", senza)
        self.add(a, "Attestati che scadono prima del completamento", "errore", prima)
        self.add(a, "Completamenti con data nel futuro", "errore", futuro,
                 "Correggere la data (o la sessione): finche' e' futura il motore non li conta.")
        self.add(a, "Attestati doppi (persona, corso, data)", "errore",
                 [f"persona {k[0]}, corso #{k[1]}, {_d(k[2])}: id {ids}" for k, ids in self._gruppi(
                     recs, lambda r: (r.legacy_anagrafica_id, r.corso_id, r.data_completamento)).items()],
                 "Tenere quello con iscrizione/attestato ed eliminare il doppione.")
        self.orfani(a, recs, desc)

        # Cache dello scadenzario: stato salvato contro quello di oggi.
        stale = []
        for t in self._qs(TrainingDeadline.objects.select_related("corso")):
            if t.data_ultimo_completamento is None:
                continue
            stato, _g = _compute_stato(t.data_scadenza, t.corso.validita_mesi or 0, self.oggi)
            if stato != t.stato_scadenza:
                stale.append(f"scadenza #{t.pk} persona {t.legacy_anagrafica_id} corso {t.corso.codice}: "
                             f"salvato {t.stato_scadenza}, oggi {stato} (scade {_d(t.data_scadenza)})")
        self.add(a, "Scadenzario formazione non aggiornato", "errore", stale,
                 "manage.py ricalcola_scadenze_hr (gira anche ogni notte).")

    @staticmethod
    def _gruppi(oggetti, chiave) -> dict:
        g = defaultdict(list)
        for o in oggetti:
            g[chiave(o)].append(o.pk)
        return {k: v for k, v in g.items() if len(v) > 1}

    # ── Qualifiche ────────────────────────────────────────────────────────
    def qualifiche(self):
        from anagrafica.models import DipendenteQualifica, _add_months

        a = "qualifiche"
        qs = self._qs(DipendenteQualifica.objects.select_related("tipo"))

        def desc(q):
            return f"qualifica #{q.pk} persona {q.legacy_anagrafica_id} «{q.tipo.nome}» del {_d(q.data_conseguimento)}"

        diverse, senza, prima, futuro, senza_data = [], [], [], [], []
        for q in qs:
            d = q.tipo.durata_mesi or 0
            att = _add_months(q.data_conseguimento, d) if (d > 0 and q.data_conseguimento) else None
            if q.data_conseguimento is None:
                senza_data.append(desc(q))
            if att and q.data_scadenza is None:
                senza.append(f"{desc(q)}: attesa {_d(att)}")
            elif att and q.data_scadenza != att:
                diverse.append(f"{desc(q)}: scade il {_d(q.data_scadenza)}, dal tipo {_d(att)}")
            if q.data_scadenza and q.data_conseguimento and q.data_scadenza < q.data_conseguimento:
                prima.append(desc(q))
            if q.data_conseguimento and q.data_conseguimento > self.oggi:
                futuro.append(desc(q))
        self.add(a, "Qualifiche senza scadenza con tipo a durata", "errore", senza)
        self.add(a, "Qualifiche con scadenza diversa dal tipo (inserita a mano?)", "avviso", diverse)
        self.add(a, "Qualifiche senza data di conseguimento", "avviso", senza_data)
        self.add(a, "Qualifiche che scadono prima del conseguimento", "errore", prima)
        self.add(a, "Qualifiche conseguite nel futuro", "errore", futuro)
        self.add(a, "Qualifiche doppie (persona, tipo, data)", "errore",
                 [f"persona {k[0]}, tipo #{k[1]}, {_d(k[2])}: id {ids}" for k, ids in self._gruppi(
                     qs, lambda q: (q.legacy_anagrafica_id, q.tipo_id, q.data_conseguimento)).items()])
        self.orfani(a, qs, desc)

    # ── DPI ───────────────────────────────────────────────────────────────
    def dpi(self):
        from dpi.models import ConsegnaDPI, RichiestaDPI

        a = "dpi"
        qs = ConsegnaDPI.objects.select_related(
            "richiesta__modello_dpi__tipo__categoria", "richiesta__categoria", "sostituita_da")
        cons = self._qs(qs, "richiesta__richiedente_legacy_id")

        def desc(c):
            return f"consegna #{c.pk} {c.richiesta.numero} persona {c.richiesta.richiedente_legacy_id} del {_d(c.data_consegna)}"

        senza, prima, futuro, attive = [], [], [], defaultdict(list)
        for c in cons:
            r = c.richiesta
            vita = r.modello_dpi.effective_vita_utile_giorni if r.modello_dpi else r.categoria.vita_utile_giorni
            if vita and c.data_scadenza_stimata is None and c.sostituita_da_id is None:
                senza.append(f"{desc(c)}: vita utile {vita} gg, attesa {_d(c.data_consegna + timedelta(days=vita))}")
            if c.data_scadenza_stimata and c.data_scadenza_stimata < c.data_consegna:
                prima.append(desc(c))
            if c.data_consegna > self.oggi:
                futuro.append(desc(c))
            tipo = r.tipo_dpi_id or (r.modello_dpi.tipo_id if r.modello_dpi else None)
            if c.sostituita_da_id is None and tipo and r.richiedente_legacy_id:
                attive[(r.richiedente_legacy_id, tipo)].append(c.pk)
        self.add(a, "Consegne attive senza scadenza ma con vita utile", "avviso", senza)
        self.add(a, "Consegne che scadono prima della consegna", "errore", prima)
        self.add(a, "Consegne con data nel futuro", "errore", futuro)
        self.add(a, "Piu' consegne attive dello stesso tipo per persona", "avviso",
                 [f"persona {k[0]}, tipo DPI #{k[1]}: consegne {ids}" for k, ids in attive.items() if len(ids) > 1],
                 "La consegna piu' recente dovrebbe sostituire le precedenti.")
        if self.id_filtro is None:
            self.add(a, "Richieste «consegnate» senza consegna registrata", "errore",
                     [f"richiesta #{pk} {num}" for pk, num in RichiestaDPI.objects.filter(
                         stato="CONSEGNATA", consegna__isnull=True).values_list("pk", "numero")])
            self.add(a, "Consegne su richieste non «consegnate»", "errore",
                     [f"{desc(c)}: stato {c.richiesta.stato}" for c in cons if c.richiesta.stato != "CONSEGNATA"])
        if self.esistenti is not None:
            self.add(a, "Persona inesistente in anagrafica", "errore",
                     [desc(c) for c in cons if c.richiesta.richiedente_legacy_id
                      and c.richiesta.richiedente_legacy_id not in self.esistenti])


def verifica(aree=AREE, legacy_ids=None, oggi: date | None = None) -> list[Sezione]:
    """Esegue i controlli richiesti e restituisce le sezioni (vuote comprese)."""
    v = _Verifica(legacy_ids, oggi)
    for area in aree:
        getattr(v, area)()
    return v.sezioni
