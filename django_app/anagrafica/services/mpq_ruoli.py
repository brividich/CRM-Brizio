"""MOD.128 — un solo sistema di ruoli sul processo.

I ruoli del modulo cartaceo (Qualificato, Addetto, Controllore, Part 145) sono
ruoli del processo (``RuoloProcesso`` con ``codice_modulo``) come quelli propri
(Operatore macchina, Ispettore…): si spuntano nello stesso elenco e decidono i
requisiti allo stesso modo. I booleani storici di ``AbilitazioneProcesso``
(``is_qualificato``…) restano come **copia calcolata** dai ruoli, perché li
leggono la vista MOD.128, l'export Word, il Dossier PART 145 e gli import: si
scrivono solo da qui (:func:`imposta_ruoli`).
"""
from __future__ import annotations

# (codice, nome, campo booleano storico), nell'ordine del modulo.
STANDARD = (
    ("QUALIFICATO", "Qualificato", "is_qualificato"),
    ("ADDETTO", "Addetto", "is_addetto"),
    ("CONTROLLORE", "Controllore", "is_controllore"),
    ("PART145", "Part 145", "is_part145"),
)
CAMPO = {c: f for c, _n, f in STANDARD}
NOME = {c: n for c, n, _f in STANDARD}


def ruolo_standard(processo, codice):
    """Ruolo standard del processo, creato se manca (adotta un ruolo con lo stesso nome)."""
    from ..models_mpq import RuoloProcesso

    r = RuoloProcesso.objects.filter(processo=processo, codice_modulo=codice).first()
    if r:
        return r
    r = RuoloProcesso.objects.filter(processo=processo, nome__iexact=NOME[codice]).first()
    if r:
        r.codice_modulo = codice
        r.save(update_fields=["codice_modulo"])
        return r
    ordine = [c for c, _n, _f in STANDARD].index(codice)
    return RuoloProcesso.objects.create(processo=processo, nome=NOME[codice], codice_modulo=codice, ordine=ordine)


def ruoli_standard_esistenti(processo) -> dict:
    """``{codice: RuoloProcesso}`` già presenti (senza crearne)."""
    return {r.codice_modulo: r for r in processo.ruoli.exclude(codice_modulo="")}


def ruoli_dal_form(processo, codici_standard, ids_propri) -> list:
    """Ruoli scelti nel form: standard per codice (creati se servono) + propri per id."""
    out = [ruolo_standard(processo, c) for c in codici_standard if c in CAMPO]
    ids = [int(x) for x in ids_propri if str(x).isdigit()]
    if ids:
        out += [r for r in processo.ruoli.filter(pk__in=ids) if r not in out]
    return out


def flag_da_ruoli(ruoli) -> dict:
    codici = {getattr(r, "codice_modulo", "") for r in ruoli}
    return {campo: (codice in codici) for codice, _n, campo in STANDARD}


def imposta_ruoli(abilitazione, ruoli) -> None:
    """Unica scrittura dei ruoli: M2M + booleani storici calcolati."""
    ruoli = list(ruoli)
    abilitazione.ruoli_processo.set(ruoli)
    flag = flag_da_ruoli(ruoli)
    cambiati = [k for k, v in flag.items() if getattr(abilitazione, k) != v]
    for k in cambiati:
        setattr(abilitazione, k, flag[k])
    if cambiati:
        abilitazione.save(update_fields=cambiati)


def allinea_da_flag(abilitazione) -> None:
    """Per gli import che scrivono ancora i booleani: aggiunge i ruoli standard corrispondenti."""
    codici_attivi = [c for c, _n, campo in STANDARD if getattr(abilitazione, campo)]
    attuali = list(abilitazione.ruoli_processo.all())
    propri = [r for r in attuali if not r.codice_modulo]
    imposta_ruoli(abilitazione, [ruolo_standard(abilitazione.processo, c) for c in codici_attivi] + propri)


def nomi_ruoli(abilitazione) -> list[str]:
    """Nomi dei ruoli della persona: prima quelli del modulo, poi i propri."""
    ordine = {c: i for i, (c, _n, _f) in enumerate(STANDARD)}
    ruoli = sorted(abilitazione.ruoli_processo.all(),
                   key=lambda r: (0 if r.codice_modulo else 1, ordine.get(r.codice_modulo, 0), r.ordine, r.nome))
    return [r.nome for r in ruoli]
