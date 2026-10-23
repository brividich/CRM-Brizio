"""Calcoli HR del modulo assenze: calendario aziendale, saldi, contatori, copertura.

Tutto in sola lettura sulla tabella legacy ``assenze`` e fail-safe: se una
sorgente manca il calcolo restituisce vuoto invece di rompere la pagina. Nessun
controllo qui blocca una richiesta: le funzioni producono **avvisi** per chi
chiede e per chi approva.

Regole di conteggio:
- una richiesta conta se non è rifiutata (approvata, programmata o in attesa);
- una richiesta a giornata intera (o su più giorni) vale i giorni lavorativi
  coperti × ``ore_giornata``; una richiesta parziale vale le sue ore, al
  massimo una giornata;
- giorni lavorativi = lunedì-venerdì (più il sabato se lavorativo), tolte le
  festività nazionali, il patrono e le chiusure aziendali;
- le chiusure aziendali con «Scala dalle ferie» tolgono i loro giorni
  lavorativi dal saldo ferie di tutti.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import connections

from core import naming
from core.legacy_utils import legacy_table_columns

from . import availability

logger = logging.getLogger(__name__)

ZERO = Decimal("0")
# Sotto questa soglia di persone un reparto non mostra i dati del cruscotto:
# con pochi dipendenti un aggregato direbbe chi era assente.
MIN_PERSONE_AGGREGATO = 5


# ─── Calendario ──────────────────────────────────────────────────────────────


def pasqua(anno: int) -> date:
    """Domenica di Pasqua (calendario gregoriano, algoritmo anonimo)."""
    a = anno % 19
    b, c = divmod(anno, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 - nome dell'algoritmo
    m = (a + 11 * h + 22 * l) // 451
    mese, giorno = divmod(h + l - 7 * m + 114, 31)
    return date(anno, mese, giorno + 1)


def festivita(anno: int, imp=None) -> dict[date, str]:
    """Festività nazionali italiane dell'anno, più il patrono se impostato."""
    out = {
        date(anno, 1, 1): "Capodanno",
        date(anno, 1, 6): "Epifania",
        date(anno, 4, 25): "Festa della Liberazione",
        date(anno, 5, 1): "Festa del Lavoro",
        date(anno, 6, 2): "Festa della Repubblica",
        date(anno, 8, 15): "Ferragosto",
        date(anno, 11, 1): "Ognissanti",
        date(anno, 12, 8): "Immacolata Concezione",
        date(anno, 12, 25): "Natale",
        date(anno, 12, 26): "Santo Stefano",
    }
    p = pasqua(anno)
    out[p] = "Pasqua"
    out[p + timedelta(days=1)] = "Lunedì dell'Angelo"
    if anno >= 2026:
        # Legge 151/2025: San Francesco d'Assisi torna festa nazionale dal 2026.
        out[date(anno, 10, 4)] = "San Francesco d'Assisi"
    if imp is not None and imp.patrono_giorno and imp.patrono_mese:
        try:
            out.setdefault(
                date(anno, int(imp.patrono_mese), int(imp.patrono_giorno)),
                f"Patrono{': ' + imp.patrono_nome if imp.patrono_nome else ''}",
            )
        except ValueError:
            logger.warning("assenze.hr: data del patrono non valida (%s/%s)", imp.patrono_giorno, imp.patrono_mese)
    return out


@dataclass
class Calendario:
    """Giorni non lavorativi di un intervallo, già pronti per i conteggi."""

    ore_giornata: Decimal
    sabato_lavorativo: bool
    festivi: dict[date, str] = field(default_factory=dict)
    chiusure: dict[date, str] = field(default_factory=dict)
    # Giorni di chiusura che scalano le ferie (sottoinsieme di ``chiusure``).
    chiusure_ferie: set[date] = field(default_factory=set)

    def settimanale(self, d: date) -> bool:
        wd = d.weekday()
        return wd < 5 or (wd == 5 and self.sabato_lavorativo)

    def lavorativo(self, d: date) -> bool:
        """Giorno in cui si lavora: niente festività, chiusure né weekend."""
        return self.settimanale(d) and d not in self.festivi and d not in self.chiusure

    def giorni_lavorativi(self, inizio: date, fine: date) -> list[date]:
        if inizio is None or fine is None or fine < inizio:
            return []
        out = []
        d = inizio
        while d <= fine:
            if self.lavorativo(d):
                out.append(d)
            d += timedelta(days=1)
        return out

    def giorni_chiusura_ferie(self, dal: date, al: date) -> list[date]:
        """Giorni lavorativi di chiusura aziendale che scalano le ferie in ``[dal, al]``."""
        return sorted(
            d for d in self.chiusure_ferie
            if dal <= d <= al and self.settimanale(d) and d not in self.festivi
        )


def impostazioni():
    from .models import AssenzeImpostazioniHR

    try:
        return AssenzeImpostazioniHR.get_solo()
    except Exception:
        logger.warning("assenze.hr: impostazioni HR non leggibili, uso i valori predefiniti", exc_info=True)
        return AssenzeImpostazioniHR(ore_giornata=Decimal("8"))


def calendario(dal: date, al: date, imp=None) -> Calendario:
    """Calendario aziendale fra ``dal`` e ``al`` (estremi compresi)."""
    from .models import ChiusuraAziendale

    imp = imp or impostazioni()
    cal = Calendario(ore_giornata=Decimal(str(imp.ore_giornata or 8)), sabato_lavorativo=bool(imp.sabato_lavorativo))
    for anno in range(dal.year, al.year + 1):
        for d, nome in festivita(anno, imp).items():
            if dal <= d <= al:
                cal.festivi[d] = nome
    try:
        chiusure = list(ChiusuraAziendale.objects.filter(data_inizio__lte=al, data_fine__gte=dal))
    except Exception:
        logger.warning("assenze.hr: chiusure aziendali non leggibili", exc_info=True)
        chiusure = []
    for ch in chiusure:
        d = max(ch.data_inizio, dal)
        while d <= min(ch.data_fine, al):
            cal.chiusure.setdefault(d, ch.descrizione)
            if ch.scala_ferie:
                cal.chiusure_ferie.add(d)
            d += timedelta(days=1)
    return cal


def eventi_calendario(dal: date, al: date) -> list[dict]:
    """Festività e chiusure come eventi di sfondo per il calendario del modulo."""
    cal = calendario(dal, al)
    out = [
        {"start": d.isoformat(), "title": nome, "display": "background", "classNames": ["abs-festivo"]}
        for d, nome in sorted(cal.festivi.items())
    ]
    out.extend(
        {"start": d.isoformat(), "title": f"Chiusura: {nome}", "display": "background", "classNames": ["abs-chiusura"]}
        for d, nome in sorted(cal.chiusure.items())
        if d not in cal.festivi
    )
    return out


# ─── Valore di una richiesta ─────────────────────────────────────────────────


def _as_dt(value) -> datetime | None:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "")[:19])
        except ValueError:
            return None
    return None


def giornata_intera(inizio: datetime, fine: datetime) -> bool:
    """Richiesta a giornate intere: più giorni, oppure 00:00-23:59."""
    if fine.date() > inizio.date():
        return True
    return inizio.hour == 0 and inizio.minute == 0 and (fine.hour, fine.minute) >= (23, 59)


def valore_richiesta(inizio, fine, cal: Calendario) -> tuple[Decimal, Decimal, list[date]]:
    """``(ore, giorni, giorni_lavorativi)`` di una richiesta nel calendario aziendale.

    Una richiesta parziale vale le sue ore (al massimo una giornata) e una
    frazione di giorno; se cade in un giorno non lavorativo non vale niente.
    """
    inizio = _as_dt(inizio)
    fine = _as_dt(fine)
    if inizio is None or fine is None or fine <= inizio:
        return ZERO, ZERO, []
    if giornata_intera(inizio, fine):
        giorni = cal.giorni_lavorativi(inizio.date(), fine.date())
        return cal.ore_giornata * len(giorni), Decimal(len(giorni)), giorni
    if not cal.lavorativo(inizio.date()):
        return ZERO, ZERO, []
    ore = Decimal(str((fine - inizio).total_seconds() / 3600)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    ore = min(ore, cal.ore_giornata)
    giorni = (ore / cal.ore_giornata).quantize(Decimal("0.01"), ROUND_HALF_UP) if cal.ore_giornata else ZERO
    return ore, giorni, [inizio.date()]


# ─── Lettura delle richieste ─────────────────────────────────────────────────


def _fetch(sql: str, params) -> list[dict]:
    with connections["default"].cursor() as cur:
        cur.execute(sql, list(params or []))
        cols = [str(c[0]) for c in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def carica_richieste(dal: date, al: date) -> list[dict]:
    """Richieste non rifiutate che toccano ``[dal, al]``, con ``stato`` calcolato.

    ``stato``: ``confermata`` (approvata o programmata) oppure ``pendente``.
    """
    try:
        cols = set(legacy_table_columns("assenze") or [])
    except Exception:
        return []
    if not {"id", "data_inizio", "data_fine"}.issubset(cols):
        return []
    sel = [c for c in (
        "id", "copia_nome", "email_esterna", "tipo_assenza", "data_inizio", "data_fine",
        "motivazione_richiesta", "consenso", "moderation_status",
    ) if c in cols]
    try:
        rows = _fetch(
            f"SELECT {', '.join(sel)} FROM assenze WHERE data_fine >= %s AND data_inizio < %s",
            [datetime(dal.year, dal.month, dal.day), datetime(al.year, al.month, al.day) + timedelta(days=1)],
        )
    except Exception:
        logger.warning("assenze.hr: lettura richieste non riuscita", exc_info=True)
        return []
    out = []
    for r in rows:
        stato = availability._classifica_stato(r.get("moderation_status"), r.get("consenso"))
        if stato is None:
            continue
        r["stato"] = stato
        out.append(r)
    return out


def tipo_richiesta(row: dict) -> str:
    from .views._helpers import _tipo_for_display

    return _tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta"))


# ─── Persone ─────────────────────────────────────────────────────────────────


@dataclass
class Indice:
    """Collega le righe ``assenze`` (nome/email) agli id dell'anagrafica."""

    identita: dict[int, dict]
    per_nome: dict[str, set[int]] = field(default_factory=dict)
    per_email: dict[str, set[int]] = field(default_factory=dict)

    @classmethod
    def per_ids(cls, ids) -> "Indice":
        try:
            ident = availability._resolve_identities(ids)
        except Exception:
            logger.warning("assenze.hr: identità anagrafica non risolte", exc_info=True)
            ident = {}
        idx = cls(identita=ident)
        for aid, info in ident.items():
            for nm in info["names"]:
                idx.per_nome.setdefault(nm, set()).add(aid)
            for em in info["emails"]:
                idx.per_email.setdefault(em, set()).add(aid)
        return idx

    def ids_riga(self, row: dict) -> set[int]:
        email = str(row.get("email_esterna") or "").strip().upper()
        if email and email in self.per_email:
            return set(self.per_email[email])
        return set(self.per_nome.get(availability._norm_key(row.get("copia_nome")), set()))

    def raggruppa(self, rows) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = {}
        for r in rows:
            for aid in self.ids_riga(r):
                out.setdefault(aid, []).append(r)
        return out


def dipendenti_attivi() -> dict[int, dict]:
    """``anagrafica_id`` → ``{"nominativo", "reparto"}`` dei dipendenti attivi.

    Il reparto è il testo dell'anagrafica (colonna ``reparto``), con il reparto
    della scheda aziendale come ripiego.
    """
    try:
        cols = set(legacy_table_columns("anagrafica_dipendenti") or [])
    except Exception:
        return {}
    if not {"id", "nome", "cognome"}.issubset(cols):
        return {}
    sel = [c for c in ("id", "nome", "cognome", "reparto") if c in cols]
    where = "WHERE attivo = 1" if "attivo" in cols else ""
    try:
        rows = _fetch(f"SELECT {', '.join(sel)} FROM anagrafica_dipendenti {where}", [])
    except Exception:
        logger.warning("assenze.hr: anagrafica non leggibile", exc_info=True)
        return {}
    out: dict[int, dict] = {}
    for r in rows:
        if r.get("id") is None:
            continue
        nominativo = naming.nome_completo(r.get("nome"), r.get("cognome"))
        if not nominativo:
            continue
        out[int(r["id"])] = {"nominativo": nominativo, "reparto": str(r.get("reparto") or "").strip()}
    senza_reparto = [aid for aid, d in out.items() if not d["reparto"]]
    if senza_reparto:
        try:
            from anagrafica.models import DipendenteAnagraficaAziendale

            for aid, area in DipendenteAnagraficaAziendale.objects.filter(
                legacy_anagrafica_id__in=senza_reparto
            ).exclude(area="").values_list("legacy_anagrafica_id", "area"):
                out[int(aid)]["reparto"] = str(area).strip()
        except Exception:
            logger.debug("assenze.hr: reparto da scheda aziendale non letto", exc_info=True)
    return out


def chiave_reparto(value) -> str:
    return " ".join(str(value or "").split()).casefold()


# ─── Saldi ───────────────────────────────────────────────────────────────────


@dataclass
class Residuo:
    saldo: object  # SaldoAssenze
    ferie_usate: Decimal = ZERO
    permessi_usati: Decimal = ZERO
    chiusure_ore: Decimal = ZERO
    in_attesa_ore: Decimal = ZERO

    @property
    def ferie_residue(self) -> Decimal:
        return Decimal(self.saldo.ferie_ore) - self.ferie_usate - self.chiusure_ore

    @property
    def permessi_residui(self) -> Decimal:
        return Decimal(self.saldo.permessi_ore) - self.permessi_usati


def residui(saldi, *, escludi_id: int | None = None, oggi: date | None = None) -> dict[int, Residuo]:
    """Residuo stimato per ogni saldo: saldo al cedolino − richieste e chiusure dopo quella data.

    Contano le richieste non rifiutate che iniziano dopo ``situazione_al``,
    anche quelle future: chi chiede deve sapere quanto gli resta davvero.
    """
    saldi = list(saldi)
    if not saldi:
        return {}
    oggi = oggi or date.today()
    dal = min(s.situazione_al for s in saldi) + timedelta(days=1)
    rows = carica_richieste(dal, oggi + timedelta(days=730))
    cal = calendario(dal, oggi + timedelta(days=730))
    per_persona = Indice.per_ids([s.legacy_anagrafica_id for s in saldi]).raggruppa(rows)
    out: dict[int, Residuo] = {}
    for s in saldi:
        res = Residuo(saldo=s)
        for r in per_persona.get(s.legacy_anagrafica_id, []):
            if escludi_id is not None and r.get("id") == escludi_id:
                continue
            inizio = _as_dt(r.get("data_inizio"))
            if inizio is None or inizio.date() <= s.situazione_al:
                continue
            tipo = tipo_richiesta(r)
            if tipo not in {"Ferie", "Permesso"}:
                continue
            ore, _giorni, _ = valore_richiesta(r.get("data_inizio"), r.get("data_fine"), cal)
            if tipo == "Ferie":
                res.ferie_usate += ore
            else:
                res.permessi_usati += ore
            if r.get("stato") == "pendente":
                res.in_attesa_ore += ore
        giorni_chiusura = cal.giorni_chiusura_ferie(s.situazione_al + timedelta(days=1), oggi + timedelta(days=730))
        res.chiusure_ore = cal.ore_giornata * len(giorni_chiusura)
        out[s.legacy_anagrafica_id] = res
    return out


def _fmt_ore(value: Decimal) -> str:
    v = Decimal(value).quantize(Decimal("0.01"), ROUND_HALF_UP).normalize()
    testo = f"{v:f}".replace(".", ",")
    return testo


def avviso_saldo(anagrafica_id: int | None, tipo: str, inizio, fine, *, escludi_id: int | None = None) -> str:
    """Avviso se la richiesta porta sotto zero ferie o permessi. Stringa vuota se va bene."""
    from .models import SaldoAssenze

    if anagrafica_id is None or tipo not in {"Ferie", "Permesso"}:
        return ""
    saldo = SaldoAssenze.objects.filter(legacy_anagrafica_id=anagrafica_id).first()
    if saldo is None:
        return ""
    res = residui([saldo], escludi_id=escludi_id).get(anagrafica_id)
    if res is None:
        return ""
    inizio_dt = _as_dt(inizio)
    if inizio_dt is None or inizio_dt.date() <= saldo.situazione_al:
        return ""
    cal = calendario(inizio_dt.date(), (_as_dt(fine) or inizio_dt).date())
    ore, _g, _ = valore_richiesta(inizio, fine, cal)
    residuo = res.ferie_residue if tipo == "Ferie" else res.permessi_residui
    if residuo - ore >= 0:
        return ""
    voce = "ferie" if tipo == "Ferie" else "permessi"
    return (
        f"Saldo {voce} insufficiente: questa richiesta vale {_fmt_ore(ore)} ore, "
        f"ne restano {_fmt_ore(residuo)} (situazione al {saldo.situazione_al.strftime('%d/%m/%Y')})."
    )


# ─── Contatori ───────────────────────────────────────────────────────────────


def _finestra(periodo: str, giorno: date) -> tuple[date, date]:
    if periodo == "mese":
        inizio = giorno.replace(day=1)
        fine = (inizio + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return inizio, fine
    return date(giorno.year, 1, 1), date(giorno.year, 12, 31)


def contatori_attivi() -> list:
    from .models import ContatoreAssenza

    try:
        return list(ContatoreAssenza.objects.filter(attivo=True))
    except Exception:
        return []


def contatore_per_motivazione(motivazione) -> object | None:
    key = naming.chiave_testo(motivazione)
    if not key:
        return None
    for c in contatori_attivi():
        if naming.chiave_testo(c.motivazione) == key:
            return c
    return None


def uso_contatore(contatore, righe_persona, finestra: tuple[date, date], cal: Calendario, *, escludi_id=None) -> Decimal:
    """Quanto la persona ha usato del contatore nella finestra (ore o giorni)."""
    key = naming.chiave_testo(contatore.motivazione)
    totale = ZERO
    dal, al = finestra
    for r in righe_persona:
        if escludi_id is not None and r.get("id") == escludi_id:
            continue
        if naming.chiave_testo(r.get("motivazione_richiesta")) != key:
            continue
        inizio = _as_dt(r.get("data_inizio"))
        if inizio is None or not (dal <= inizio.date() <= al):
            continue
        ore, giorni, _ = valore_richiesta(r.get("data_inizio"), r.get("data_fine"), cal)
        totale += ore if contatore.unita == "ore" else giorni
    return totale


def avviso_contatore(anagrafica_id: int | None, motivazione, inizio, fine, *, escludi_id: int | None = None) -> str:
    """Avviso se la richiesta supera il limite del contatore della sua motivazione."""
    contatore = contatore_per_motivazione(motivazione)
    inizio_dt = _as_dt(inizio)
    if contatore is None or anagrafica_id is None or inizio_dt is None:
        return ""
    finestra = _finestra(contatore.periodo, inizio_dt.date())
    cal = calendario(finestra[0], finestra[1])
    righe = Indice.per_ids([anagrafica_id]).raggruppa(carica_richieste(*finestra)).get(anagrafica_id, [])
    usato = uso_contatore(contatore, righe, finestra, cal, escludi_id=escludi_id)
    ore, giorni, _ = valore_richiesta(inizio, fine, cal)
    questa = ore if contatore.unita == "ore" else giorni
    limite = Decimal(contatore.limite)
    if usato + questa <= limite:
        return ""
    periodo = "nel mese" if contatore.periodo == "mese" else "nell'anno"
    return (
        f"{contatore.nome}: con questa richiesta si arriva a {_fmt_ore(usato + questa)} {contatore.unita} "
        f"{periodo}, il limite è {_fmt_ore(limite)}."
    )


def riepilogo_contatori(oggi: date | None = None) -> list[dict]:
    """Per ogni contatore attivo: chi l'ha usato nel periodo corrente e chi supera il limite."""
    oggi = oggi or date.today()
    contatori = contatori_attivi()
    if not contatori:
        return []
    dal = date(oggi.year, 1, 1)
    al = date(oggi.year, 12, 31)
    rows = carica_richieste(dal, al)
    cal = calendario(dal, al)
    attivi = dipendenti_attivi()
    per_persona = Indice.per_ids(list(attivi)).raggruppa(rows)
    out = []
    for c in contatori:
        finestra = _finestra(c.periodo, oggi)
        persone = []
        for aid, righe in per_persona.items():
            usato = uso_contatore(c, righe, finestra, cal)
            if usato <= 0:
                continue
            persone.append({
                "anagrafica_id": aid,
                "nominativo": attivi.get(aid, {}).get("nominativo", f"#{aid}"),
                "usato": usato,
                "oltre": usato > Decimal(c.limite),
            })
        persone.sort(key=lambda p: (not p["oltre"], -p["usato"], p["nominativo"]))
        out.append({
            "contatore": c,
            "finestra": finestra,
            "persone": persone,
            "oltre": sum(1 for p in persone if p["oltre"]),
        })
    return out


# ─── Copertura del reparto ───────────────────────────────────────────────────


def avvisi_copertura(rows: list[dict]) -> dict[int, str]:
    """Per le richieste in coda: avviso se approvarle porta il reparto oltre la soglia.

    Conta, giorno per giorno, i colleghi dello stesso reparto già assenti a
    giornata intera con una richiesta confermata, più la richiesta stessa.
    """
    from .models import SogliaCopertura

    try:
        soglie = {chiave_reparto(s.reparto): s for s in SogliaCopertura.objects.all()}
    except Exception:
        return {}
    if not soglie or not rows:
        return {}
    attivi = dipendenti_attivi()
    indice = Indice.per_ids(list(attivi))
    reparto_di = {aid: chiave_reparto(d["reparto"]) for aid, d in attivi.items()}

    date_inizio = [d for d in (_as_dt(r.get("data_inizio")) for r in rows) if d]
    date_fine = [d for d in (_as_dt(r.get("data_fine")) for r in rows) if d]
    if not date_inizio or not date_fine:
        return {}
    dal, al = min(date_inizio).date(), max(date_fine).date()
    cal = calendario(dal, al)
    confermate = [r for r in carica_richieste(dal, al) if r.get("stato") == "confermata"]

    # giorno → reparto → persone assenti a giornata intera
    assenti: dict[date, dict[str, set[int]]] = {}
    for r in confermate:
        inizio, fine = _as_dt(r.get("data_inizio")), _as_dt(r.get("data_fine"))
        if inizio is None or fine is None or not giornata_intera(inizio, fine):
            continue
        for aid in indice.ids_riga(r):
            rep = reparto_di.get(aid)
            if not rep or rep not in soglie:
                continue
            for d in cal.giorni_lavorativi(inizio.date(), fine.date()):
                assenti.setdefault(d, {}).setdefault(rep, set()).add(aid)

    out: dict[int, str] = {}
    for r in rows:
        rid = r.get("id")
        inizio, fine = _as_dt(r.get("data_inizio")), _as_dt(r.get("data_fine"))
        if rid is None or inizio is None or fine is None:
            continue
        persone = indice.ids_riga({"copia_nome": r.get("copia_nome") or r.get("dipendente"),
                                   "email_esterna": r.get("email_esterna")})
        for aid in persone:
            rep = reparto_di.get(aid)
            soglia = soglie.get(rep) if rep else None
            if soglia is None:
                continue
            peggiore = None
            for d in cal.giorni_lavorativi(inizio.date(), fine.date()) or [inizio.date()]:
                altri = assenti.get(d, {}).get(rep, set()) - {aid}
                totale = len(altri) + 1
                if totale > soglia.max_assenti and (peggiore is None or totale > peggiore[1]):
                    peggiore = (d, totale)
            if peggiore:
                out[int(rid)] = (
                    f"Copertura {soglia.reparto}: il {peggiore[0].strftime('%d/%m')} sarebbero assenti "
                    f"{peggiore[1]} persone (soglia {soglia.max_assenti})."
                )
            break
    return out


def avviso_chiusure(inizio, fine) -> str:
    """Avviso se nel periodo ci sono festività o chiusure aziendali (non contano nella richiesta)."""
    inizio_dt, fine_dt = _as_dt(inizio), _as_dt(fine)
    if inizio_dt is None or fine_dt is None or fine_dt < inizio_dt:
        return ""
    cal = calendario(inizio_dt.date(), fine_dt.date())
    giorni = [d for d in sorted(set(cal.festivi) | set(cal.chiusure)) if cal.settimanale(d)]
    if not giorni:
        return ""
    if not cal.giorni_lavorativi(inizio_dt.date(), fine_dt.date()):
        return "Nel periodo l'azienda è chiusa o è festa: la richiesta non conta nessun giorno lavorativo."
    nomi = ", ".join(f"{d.strftime('%d/%m')} {cal.chiusure.get(d) or cal.festivi.get(d)}" for d in giorni[:4])
    return f"Nel periodo ci sono giorni non lavorativi che non contano: {nomi}."


def avvisi_richiesta(*, anagrafica_id, tipo, motivazione, inizio, fine, escludi_id=None) -> list[str]:
    """Tutti i controlli HR su una richiesta, come avvisi. Fail-safe: un errore non blocca l'invio."""
    out = []
    for controllo in (
        lambda: avviso_saldo(anagrafica_id, tipo, inizio, fine, escludi_id=escludi_id),
        lambda: avviso_contatore(anagrafica_id, motivazione, inizio, fine, escludi_id=escludi_id),
        lambda: avviso_chiusure(inizio, fine),
    ):
        try:
            testo = controllo()
        except Exception:
            logger.warning("assenze.hr: controllo della richiesta non riuscito", exc_info=True)
            continue
        if testo:
            out.append(testo)
    return out


def riepilogo_saldo(anagrafica_id) -> dict | None:
    """Saldo e residuo stimato di una persona, per il riquadro nel form di richiesta."""
    from .models import SaldoAssenze

    if anagrafica_id is None:
        return None
    try:
        saldo = SaldoAssenze.objects.filter(legacy_anagrafica_id=anagrafica_id).first()
        if saldo is None:
            return None
        res = residui([saldo]).get(anagrafica_id)
    except Exception:
        logger.warning("assenze.hr: saldo non calcolato per %s", anagrafica_id, exc_info=True)
        return None
    if res is None:
        return None
    return {
        "situazione_al": saldo.situazione_al.strftime("%d/%m/%Y"),
        "ferie_residue": _fmt_ore(res.ferie_residue),
        "permessi_residui": _fmt_ore(res.permessi_residui),
        "ferie_negative": res.ferie_residue < 0,
        "permessi_negativi": res.permessi_residui < 0,
        "in_attesa": _fmt_ore(res.in_attesa_ore),
    }


def annota_coda(rows: list[dict]) -> None:
    """Aggiunge ``avvisi_hr`` alle righe della coda del capo: saldo, contatori, copertura.

    Le righe sono quelle di ``_load_pending_for_manager`` (``dipendente``,
    ``data_inizio_raw``…). Gli avvisi non bloccano niente: dicono a chi approva
    cosa sta per succedere. Fail-safe: un errore lascia la coda senza avvisi.
    """
    if not rows:
        return
    for r in rows:
        r.setdefault("avvisi_hr", [])
    try:
        from .models import SaldoAssenze

        grezze = [
            {
                "id": r.get("id"),
                "copia_nome": r.get("dipendente"),
                "email_esterna": r.get("email_esterna"),
                "data_inizio": r.get("data_inizio_raw"),
                "data_fine": r.get("data_fine_raw"),
                "motivazione_richiesta": r.get("motivo"),
            }
            for r in rows
        ]
        attivi = dipendenti_attivi()
        indice = Indice.per_ids(list(attivi))
        aid_riga = {}
        for g in grezze:
            ids = indice.ids_riga(g)
            if len(ids) == 1:
                aid_riga[g["id"]] = next(iter(ids))

        saldi = list(SaldoAssenze.objects.filter(legacy_anagrafica_id__in=set(aid_riga.values())))
        res = residui(saldi)
        copertura = avvisi_copertura(grezze)

        contatori = contatori_attivi()
        cont_cache: dict[tuple, Decimal] = {}
        for r, g in zip(rows, grezze, strict=True):
            aid = aid_riga.get(g["id"])
            tipo = str(r.get("tipo") or "")
            if aid in res and tipo in {"Ferie", "Permesso"}:
                residuo = res[aid].ferie_residue if tipo == "Ferie" else res[aid].permessi_residui
                if residuo < 0:
                    voce = "ferie" if tipo == "Ferie" else "permessi"
                    r["avvisi_hr"].append(
                        f"Saldo {voce}: contando le richieste in attesa mancano {_fmt_ore(-residuo)} ore."
                    )
            key = naming.chiave_testo(g["motivazione_richiesta"])
            cont = next((c for c in contatori if key and naming.chiave_testo(c.motivazione) == key), None)
            inizio = _as_dt(g["data_inizio"])
            if cont is not None and aid is not None and inizio is not None:
                finestra = _finestra(cont.periodo, inizio.date())
                ck = (cont.pk, aid, finestra)
                if ck not in cont_cache:
                    cal = calendario(*finestra)
                    righe = indice.raggruppa(carica_richieste(*finestra)).get(aid, [])
                    cont_cache[ck] = uso_contatore(cont, righe, finestra, cal)
                if cont_cache[ck] > Decimal(cont.limite):
                    periodo = "nel mese" if cont.periodo == "mese" else "nell'anno"
                    r["avvisi_hr"].append(
                        f"{cont.nome}: {_fmt_ore(cont_cache[ck])} {cont.unita} {periodo}, "
                        f"oltre il limite di {_fmt_ore(Decimal(cont.limite))}."
                    )
            if g["id"] in copertura:
                r["avvisi_hr"].append(copertura[g["id"]])
    except Exception:
        logger.warning("assenze.hr: avvisi della coda non calcolati", exc_info=True)


# ─── Cruscotto HR ────────────────────────────────────────────────────────────


def _mesi_indietro(oggi: date, n: int) -> list[date]:
    primo = oggi.replace(day=1)
    out = []
    for _ in range(n):
        out.append(primo)
        primo = (primo - timedelta(days=1)).replace(day=1)
    return list(reversed(out))


def cruscotto(oggi: date | None = None, mesi: int = 12) -> dict:
    """Numeri aggregati dell'azienda e dei reparti. Niente indicatori per persona.

    I reparti con meno di ``MIN_PERSONE_AGGREGATO`` dipendenti non mostrano i
    numeri: con pochi colleghi un totale direbbe chi era assente.
    """
    oggi = oggi or date.today()
    inizio_mesi = _mesi_indietro(oggi, mesi)
    dal = inizio_mesi[0]
    al = oggi
    rows = [r for r in carica_richieste(dal, al) if r.get("stato") == "confermata"]
    cal = calendario(dal, al)
    attivi = dipendenti_attivi()
    indice = Indice.per_ids(list(attivi))
    n_persone = len(attivi)

    categorie = ("Ferie", "Permesso", "Malattia", "Altre")

    def categoria(row) -> str | None:
        tipo = tipo_richiesta(row)
        if tipo in {"Certifica presenza", "Flessibilità"}:
            return None
        return tipo if tipo in {"Ferie", "Permesso", "Malattia"} else "Altre"

    per_mese = {m: dict.fromkeys(categorie, ZERO) for m in inizio_mesi}
    anno_inizio = date(oggi.year, 1, 1)
    reparti: dict[str, dict] = {}
    for d in attivi.values():
        rep = d["reparto"] or "Senza reparto"
        reparti.setdefault(rep, {"reparto": rep, "persone": 0, **dict.fromkeys(categorie, ZERO)})["persone"] += 1

    for r in rows:
        cat = categoria(r)
        if cat is None:
            continue
        inizio, fine = _as_dt(r.get("data_inizio")), _as_dt(r.get("data_fine"))
        if inizio is None or fine is None:
            continue
        # Giorni dentro la finestra, attribuiti al mese di ciascun giorno.
        _ore, _giorni, giorni_lav = valore_richiesta(inizio, fine, cal)
        if not giorni_lav:
            continue
        quota = (_giorni / len(giorni_lav)) if giorni_lav else ZERO
        persone = indice.ids_riga(r)
        for g in giorni_lav:
            if not (dal <= g <= al):
                continue
            mese = g.replace(day=1)
            if mese in per_mese:
                per_mese[mese][cat] += quota
            if g >= anno_inizio:
                for aid in persone:
                    rep = attivi.get(aid, {}).get("reparto") or "Senza reparto"
                    if rep in reparti:
                        reparti[rep][cat] += quota

    giorni_anno = len(cal.giorni_lavorativi(anno_inizio, oggi))
    elenco_reparti = []
    for rep in sorted(reparti.values(), key=lambda x: x["reparto"].casefold()):
        visibile = rep["persone"] >= MIN_PERSONE_AGGREGATO
        teorici = rep["persone"] * giorni_anno
        assenze_non_ferie = rep["Malattia"] + rep["Altre"]
        elenco_reparti.append({
            **rep,
            "visibile": visibile,
            "tasso": (assenze_non_ferie * 100 / teorici).quantize(Decimal("0.1")) if visibile and teorici else None,
        })

    totale_anno = {c: sum((r[c] for r in reparti.values()), ZERO) for c in categorie}
    teorici_azienda = n_persone * giorni_anno
    massimo_mese = max((sum(v.values(), ZERO) for v in per_mese.values()), default=ZERO)
    return {
        "categorie": categorie,
        "mesi": [
            {"mese": m, "valori": v, "totale": sum(v.values(), ZERO)}
            for m, v in per_mese.items()
        ],
        "massimo_mese": massimo_mese,
        "reparti": elenco_reparti,
        "persone": n_persone,
        "giorni_lavorativi_anno": giorni_anno,
        "totale_anno": totale_anno,
        "tasso_azienda": (
            ((totale_anno["Malattia"] + totale_anno["Altre"]) * 100 / teorici_azienda).quantize(Decimal("0.1"))
            if teorici_azienda else None
        ),
        "min_persone": MIN_PERSONE_AGGREGATO,
    }


# ─── Storico modifiche ───────────────────────────────────────────────────────

CAMPI_STORICO = {
    "tipo_assenza": "Tipo",
    "data_inizio": "Inizio",
    "data_fine": "Fine",
    "motivazione_richiesta": "Motivazione",
    "certificato_medico": "Certificato medico",
    "consenso": "Stato",
    "note_gestione": "Nota",
}


def _testo_valore(value) -> str:
    if value is None:
        return ""
    dt = value if isinstance(value, datetime) else None
    if isinstance(value, str) and len(value) >= 16 and value[4:5] == "-" and value[10:11] in {" ", "T"}:
        # Il DB legacy può restituire le date come testo ISO: stesso formato delle altre.
        dt = _as_dt(value)
    if dt is not None:
        if dt.tzinfo:
            from django.utils import timezone as dj_tz

            dt = dj_tz.localtime(dt).replace(tzinfo=None)
        if (dt.hour, dt.minute) == (0, 0):
            return dt.strftime("%d/%m/%Y")
        return dt.strftime("%d/%m/%Y %H:%M")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return str(value).strip()


def differenze(prima: dict | None, dopo: dict) -> list[dict]:
    """Campi cambiati fra due versioni di una riga, con etichetta leggibile."""
    prima = prima or {}
    out = []
    for campo, etichetta in CAMPI_STORICO.items():
        if campo not in dopo:
            continue
        a, b = _testo_valore(prima.get(campo)), _testo_valore(dopo.get(campo))
        if a != b:
            out.append({"campo": etichetta, "prima": a, "dopo": b})
    return out


def registra(assenza_id, azione: str, *, utente: str = "", prima: dict | None = None,
             dopo: dict | None = None, motivo: str = "") -> None:
    """Scrive una riga di storico. Best-effort: un errore non annulla l'operazione."""
    from .models import AssenzaModifica

    try:
        item_id = int(assenza_id)
    except (TypeError, ValueError):
        return
    try:
        AssenzaModifica.objects.create(
            assenza_id=item_id,
            azione=azione,
            utente=str(utente or "")[:200],
            modifiche=differenze(prima, dopo or {}) if dopo is not None else [],
            motivo=str(motivo or "").strip(),
        )
    except Exception:
        logger.warning("assenze.hr: storico non registrato per assenza %s", assenza_id, exc_info=True)
