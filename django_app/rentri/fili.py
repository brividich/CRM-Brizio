"""Filo conduttore del registro: ogni carico con i suoi scarichi, il residuo e lo stato.

È l'unico posto che risponde a «quanto resta di questo carico?» e «a che punto è
il suo ciclo?». Lo usano la giacenza, i movimenti collegabili del wizard, la
validazione degli scarichi, l'elenco a famiglie e la verifica.

Come si registra davvero (registro di produzione, 2025-2026)::

    C  carico            +3200   il rifiuto entra nel deposito temporaneo
    O  scarico originale −3200   parte con il FIR: esce dal deposito
    M  scarico effettivo −5420   peso verificato a destino (quarta copia)
    R  rettifica         +5420   la coppia M/R corregge il peso, non il deposito

Regole del conto:

- il **codice** si confronta per le sei cifre del CER (:func:`chiave`): lo storico
  scrive «12.01.01 Sfridi Ferro Kg», il catalogo e la lettura del FIR «12 01 01»;
- l'**uscita** dal deposito è lo scarico originale O (in valore assoluto: il segno
  nel registro è libero). Uno scarico effettivo M conta come uscita solo se nel
  suo filo non c'è una O (storico registrato senza scarico originale);
- la rettifica R non muove il deposito: corregge il peso dello scarico;
- un'uscita **collegata** consuma i propri carichi, dal più vecchio; quello che
  avanza è un'eccedenza (scarico oltre il carico collegato) e non tocca gli altri
  carichi. Un'uscita **non collegata** consuma i carichi dello stesso codice dal
  più vecchio (FIFO), solo quelli con data uguale o precedente alla sua; quello
  che avanza è un'eccedenza del codice;
- i movimenti annullati non contano: i figli di un movimento annullato restano
  con il loro Rif. Op (traccia) ma non risultano più collegati.

⚠️ Semantica da validare col responsabile ambientale: è isolata qui apposta.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .catena import indice_per_id, risali_a_carichi, split_rif_op
from .validazione import normalizza_cer

__all__ = [
    "EPS",
    "chiave",
    "valore",
    "Analisi",
    "analizza",
    "analizza_codice",
    "fili_del_codice",
    "stato_filo",
]

EPS = Decimal("0.0005")


def chiave(codice: str) -> str:
    """Le sei cifre del CER (``"120101"``): tutti i conti per codice passano da qui."""
    return normalizza_cer(codice)


def valore(r) -> Decimal | None:
    """Quantità dichiarata dal movimento: ``quantita``, altrimenti ``rettifica_scarico``."""
    return r.quantita if r.quantita is not None else r.rettifica_scarico


def gia_presente(carico, scarico) -> bool:
    """Il carico c'era già alla data dello scarico (date mancanti: sì)."""
    return not carico.data or not scarico.data or carico.data <= scarico.data


def _ordine(r):
    return (r.data or date.min, r.pk or 0)


@dataclass
class Analisi:
    """Risultato del conto su un insieme di movimenti validi."""

    residuo: dict[int, Decimal] = field(default_factory=dict)       # pk carico → residuo
    carichi: dict[str, list] = field(default_factory=dict)          # chiave → carichi in ordine
    collegati: dict[int, list[int]] = field(default_factory=dict)   # pk movimento → pk carichi del suo filo
    uscita: dict[int, Decimal] = field(default_factory=dict)        # pk movimento → uscita dal deposito
    eccedenze: list[tuple] = field(default_factory=list)            # (movimento, quantità, collegato?)
    figli: dict[int, list] = field(default_factory=dict)            # pk carico → movimenti del filo

    def giacenza(self, codice: str) -> Decimal:
        k = chiave(codice)
        return sum((self.residuo[c.pk] for c in self.carichi.get(k, [])), Decimal(0))

    def entrate(self, codice: str) -> Decimal:
        return sum((Decimal(c.quantita or 0) for c in self.carichi.get(chiave(codice), [])), Decimal(0))


def analizza(records) -> Analisi:
    """Conto del deposito su `records` (movimenti **validi**, di uno o più codici)."""
    records = [r for r in records if not r.annullato]
    by_id = indice_per_id(records)
    a = Analisi()

    for r in sorted((r for r in records if r.tipo == "C"), key=_ordine):
        a.carichi.setdefault(chiave(r.codice), []).append(r)
        a.residuo[r.pk] = max(Decimal(r.quantita or 0), Decimal(0))
        a.figli[r.pk] = []

    def _carichi_di(r) -> list[int]:
        k = chiave(r.codice)
        pks: list[int] = []
        for cid in risali_a_carichi(r.rif_op, by_id):
            for c in by_id.get(cid, []):
                if c.tipo == "C" and chiave(c.codice) == k and c.pk not in pks:
                    pks.append(c.pk)
        return pks

    altri = sorted((r for r in records if r.tipo != "C"), key=_ordine)
    for r in altri:
        a.collegati[r.pk] = _carichi_di(r)
        for pk in a.collegati[r.pk]:
            a.figli[pk].append(r)

    carichi_con_o = {pk for r in altri if r.tipo == "O" for pk in a.collegati[r.pk]}

    def _cita_o(r) -> bool:
        return any(g.tipo == "O" for rid in split_rif_op(r.rif_op) for g in by_id.get(rid, []))

    uscite = []
    for r in altri:
        v = valore(r)
        if not v:
            continue
        if r.tipo == "O" or (
            r.tipo == "M" and not _cita_o(r) and not any(pk in carichi_con_o for pk in a.collegati[r.pk])
        ):
            a.uscita[r.pk] = abs(Decimal(v))
            uscite.append(r)

    def _consuma(pks: list[int], q: Decimal) -> Decimal:
        for pk in pks:
            if q <= 0:
                break
            preso = min(a.residuo[pk], q)
            a.residuo[pk] -= preso
            q -= preso
        return q

    per_pk = {c.pk: c for lst in a.carichi.values() for c in lst}
    # Prima le uscite collegate (consumano i propri carichi), poi le altre in FIFO.
    for r in uscite:
        pks = sorted(a.collegati[r.pk], key=lambda pk: _ordine(per_pk[pk]))
        if pks:
            resto = _consuma(pks, a.uscita[r.pk])
            if resto > EPS:
                a.eccedenze.append((r, resto, True))
    for r in uscite:
        if a.collegati[r.pk]:
            continue
        # Solo i carichi che esistevano già alla data dello scarico: uno scarico del
        # 2025 non può consumare un carico del 2026.
        resto = _consuma([c.pk for c in a.carichi.get(chiave(r.codice), []) if gia_presente(c, r)], a.uscita[r.pk])
        if resto > EPS:
            a.eccedenze.append((r, resto, False))
    return a


def analizza_codice(codice: str, *, escludi_pk=None) -> Analisi:
    """Conto dei movimenti validi del solo codice indicato (per le sei cifre)."""
    from .models import RegistroRifiuti

    k = chiave(codice)
    qs = RegistroRifiuti.objects.attivi().exclude(codice="")
    if escludi_pk:
        qs = qs.exclude(pk=escludi_pk)
    return analizza([r for r in qs if chiave(r.codice) == k])


def stato_filo(carico, a: Analisi) -> str:
    """``deposito`` (residuo da scaricare) · ``attesa_m`` (uscito, manca lo scarico effettivo) · ``chiuso``."""
    if a.residuo.get(carico.pk, Decimal(0)) > EPS:
        return "deposito"
    tipi = {f.tipo for f in a.figli.get(carico.pk, [])}
    return "chiuso" if "M" in tipi else "attesa_m"


ETICHETTE_STATO = {
    "deposito": "In deposito",
    "attesa_m": "Manca lo scarico effettivo",
    "chiuso": "Chiuso",
}


def _fmt_data(d) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def _num(q) -> float | None:
    return float(q) if q is not None else None


def fili_del_codice(codice: str, tipo: str, *, tutti: bool = False, escludi_pk=None) -> list[dict]:
    """Movimenti collegabili a un nuovo movimento `tipo` (O, M, R) del codice indicato.

    Una voce per filo, sempre con il **carico** in vista:

    - O → i carichi con un residuo da scaricare; si collega il carico;
    - M → i fili usciti senza scarico effettivo: si collega lo scarico originale O
      (il carico senza O compare solo con ``tutti``);
    - R → i fili con uno scarico effettivo senza rettifica: si collega l'M.

    Con ``tutti`` compaiono anche i fili già completi per quel passo (marcati
    ``gia_collegato``): il collegamento resta una scelta della persona, la
    validazione decide se è ammesso.
    """
    tipo = (tipo or "").upper()
    if tipo not in ("O", "M", "R") or not chiave(codice):
        return []
    a = analizza_codice(codice, escludi_pk=escludi_pk)
    out: list[dict] = []
    for c in a.carichi.get(chiave(codice), []):
        figli = a.figli.get(c.pk, [])
        o_list = [f for f in figli if f.tipo == "O"]
        m_list = [f for f in figli if f.tipo == "M"]
        r_list = [f for f in figli if f.tipo == "R"]
        residuo = a.residuo[c.pk]
        base = {
            "carico": c.id_registrazione,
            "_ord": _ordine(c),
            "carico_data": _fmt_data(c.data),
            "carico_quantita": _num(c.quantita),
            "residuo": _num(residuo),
            "unita": c.unita,
            "stato": stato_filo(c, a),
            "stato_label": ETICHETTE_STATO[stato_filo(c, a)],
            "scarichi": [f"{f.tipo} {f.id_registrazione}" for f in figli],
        }
        if tipo == "O":
            libero = residuo > EPS
            if libero or tutti:
                out.append({**base, "id_registrazione": c.id_registrazione, "tipo": "C",
                            "data": _fmt_data(c.data), "quantita": _num(residuo if libero else c.quantita),
                            "gia_collegato": not libero})
            continue
        if tipo == "M":
            # Senza O il carico compare solo con «tutti»: di norma lo scarico effettivo
            # segue uno scarico originale (lo storico però ha M agganciate al carico).
            genitori = o_list or ([c] if tutti else [])
            for g in genitori:
                m_di_g = [m for m in m_list if g.id_registrazione in split_rif_op(m.rif_op)] if g.tipo == "O" else m_list
                gia = bool(m_di_g) or (g.tipo == "O" and bool(m_list) and len(o_list) == 1)
                if gia and not tutti:
                    continue
                v = valore(g)
                out.append({**base, "id_registrazione": g.id_registrazione, "tipo": g.tipo,
                            "data": _fmt_data(g.data), "quantita": _num(abs(v) if v is not None else None),
                            "fir": g.arrivo_fir, "gia_collegato": gia})
            continue
        # R: si rettifica uno scarico effettivo.
        for m in m_list:
            gia = any(m.id_registrazione in split_rif_op(r.rif_op) for r in r_list) or (
                len(m_list) == 1 and bool(r_list)
            )
            if gia and not tutti:
                continue
            v = valore(m)
            out.append({**base, "id_registrazione": m.id_registrazione, "tipo": "M",
                        "data": _fmt_data(m.data), "quantita": _num(abs(v) if v is not None else None),
                        "fir": m.arrivo_fir, "gia_collegato": gia})
    # Uno stesso O/M può stare in più fili (scarico su più carichi): una voce sola.
    unici: dict[str, dict] = {}
    for voce in out:
        prima = unici.get(voce["id_registrazione"])
        if prima is None:
            voce["carichi"] = [voce["carico"]]
            unici[voce["id_registrazione"]] = voce
        elif voce["carico"] not in prima["carichi"]:
            prima["carichi"].append(voce["carico"])
    # Prima i collegabili, poi i già collegati; dentro ogni gruppo il più recente in alto.
    voci = sorted(unici.values(), key=lambda v: v["_ord"], reverse=True)
    voci.sort(key=lambda v: v["gia_collegato"])
    for v in voci:
        del v["_ord"]
    return voci
