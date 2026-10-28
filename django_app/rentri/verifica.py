"""Verifica di coerenza del registro RENTRI (sola lettura).

Raccoglie in un posto solo le anomalie che il salvataggio ora impedisce ma che
lo storico può ancora contenere, più gli adempimenti con un termine:

- scarichi senza carico d'origine e catene con CER diversi;
- movimenti datati prima del movimento a cui si collegano;
- saldo del deposito che va sotto zero (uno scarico registrato prima del carico);
- numeri di registrazione doppi (escluse le coppie R+M dello stesso giorno);
- scarichi originali senza scarico effettivo dopo 90 giorni (quarta copia del FIR);
- annotazioni scritte oltre 10 giorni lavorativi dal movimento (solo quelle del portale);
- giacenze oltre soglia, codici con unità di misura miste, copie SharePoint non allineate.

I termini (10 giorni lavorativi, 90 giorni) sono quelli dell'art. 190 e del
formulario: da confermare col responsabile ambientale, sono costanti qui sotto.
Gli annullati non entrano in nessun controllo.

Usata dalla pagina ``/rentri/verifica/``, dal comando ``rentri_verifica`` e
dall'avviso periodico ``check_rentri_scadenze``.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from .catena import indice_per_id, risali_a_carichi, split_rif_op
from .giacenze import chiave_codice, contributo, giacenze_per_cer, soglie_deposito
from .models import RegistroRifiuti
from .validazione import normalizza_cer

__all__ = ["GIORNI_LAVORATIVI_ANNOTAZIONE", "GIORNI_QUARTA_COPIA", "verifica_registro", "conteggi", "verifica_csv"]

GIORNI_LAVORATIVI_ANNOTAZIONE = 10
GIORNI_QUARTA_COPIA = 90


def _riga(r, dettaglio: str) -> dict:
    return {
        "pk": r.pk,
        "id_registrazione": r.id_registrazione,
        "tipo": r.tipo,
        "data": r.data,
        "codice": r.codice,
        "dettaglio": dettaglio,
    }


def _giorni_lavorativi(da: date, a: date) -> int:
    """Giorni lavorativi (lun-ven) dopo `da` fino ad `a` compreso."""
    if a <= da:
        return 0
    giorni = 0
    giorno = da
    while giorno < a:
        giorno += timedelta(days=1)
        if giorno.weekday() < 5:
            giorni += 1
    return giorni


def _catene(records: list, by_id: dict) -> tuple[list, list, list]:
    orfani, cer_misti, date_errate = [], [], []
    for r in records:
        if r.tipo == "C":
            continue
        refs = split_rif_op(r.rif_op)
        carichi = risali_a_carichi(r.rif_op, by_id)
        if not carichi:
            dettaglio = f"Rif. Op «{r.rif_op}» non porta a nessun carico" if refs else "Nessun movimento collegato"
            orfani.append(_riga(r, dettaglio))
        else:
            cer = normalizza_cer(r.codice)
            diversi = sorted({
                c.codice for cid in carichi for c in by_id.get(cid, [])
                if c.tipo == "C" and normalizza_cer(c.codice) != cer
            })
            if diversi:
                cer_misti.append(_riga(r, f"Il carico d'origine ha codice {', '.join(diversi)}"))
        for rid in refs:
            for g in by_id.get(rid, []):
                if g.pk != r.pk and g.data and r.data and r.data < g.data:
                    date_errate.append(_riga(r, f"Datato prima di {g.tipo} {rid} del {g.data:%d/%m/%Y}"))
                    break
    return orfani, cer_misti, date_errate


def _saldi_negativi(records: list) -> list:
    """Primo movimento che porta sotto zero il saldo di un codice, in ordine di data."""
    per_codice: dict[str, list] = defaultdict(list)
    for r in records:
        if r.tipo in ("C", "M", "R") and chiave_codice(r.codice):
            per_codice[chiave_codice(r.codice)].append(r)
    ordine = {"C": 0, "R": 1, "M": 2}
    righe = []
    for movimenti in per_codice.values():
        saldo = Decimal(0)
        for r in sorted(movimenti, key=lambda m: (m.data or date.min, ordine[m.tipo], m.pk)):
            entrata, uscita = contributo(r)
            saldo += entrata - uscita
            if saldo < Decimal("-0.0005"):
                righe.append(_riga(r, f"Dopo questo movimento il saldo è {saldo:.3f}: manca un carico precedente"))
                break
    return righe


def _quarte_copie(records: list, oggi: date) -> list:
    m_citati: set[str] = set()
    m_rif: set[str] = set()
    for r in records:
        if r.tipo == "M":
            m_citati.update(split_rif_op(r.rif_op))
            m_rif.add(", ".join(split_rif_op(r.rif_op)))
    righe = []
    for r in records:
        if r.tipo != "O" or not r.data:
            continue
        giorni = (oggi - r.data).days
        if giorni <= GIORNI_QUARTA_COPIA:
            continue
        if r.id_registrazione in m_citati or ", ".join(split_rif_op(r.rif_op)) in m_rif:
            continue
        righe.append(_riga(r, f"Partito da {giorni} giorni, nessuno scarico effettivo (M) registrato"))
    return righe


def _annotazioni_tardive(records: list) -> list:
    righe = []
    for r in records:
        if r.origine != "portale" or not r.data or not r.created_at:
            continue
        scritto = timezone.localtime(r.created_at).date()
        ritardo = _giorni_lavorativi(r.data, scritto)
        if ritardo > GIORNI_LAVORATIVI_ANNOTAZIONE:
            righe.append(_riga(r, f"Registrato il {scritto:%d/%m/%Y}, {ritardo} giorni lavorativi dopo il movimento"))
    return righe


def _duplicati() -> list:
    from .numerazione import id_duplicati

    righe = []
    for g in id_duplicati():
        if g["coppia_rm"]:
            continue
        attive = [r for r in g["righe"] if not r.annullato]
        if len(attive) < 2:
            continue
        tipi = " + ".join(r.tipo for r in attive)
        for r in attive:
            righe.append(_riga(r, f"Numero usato da {len(attive)} movimenti ({tipi})"))
    return righe


def verifica_registro() -> list[dict]:
    """Le sezioni della verifica, ognuna con le sue righe (vuote = nessuna anomalia)."""
    oggi = timezone.localdate()
    records = list(RegistroRifiuti.objects.attivi().order_by("data", "id"))
    by_id = indice_per_id(records)
    orfani, cer_misti, date_errate = _catene(records, by_id)

    soglie = soglie_deposito()
    deposito, unita_miste = [], []
    for g in giacenze_per_cer():
        tono = g.tono(soglie)
        base = {"pk": None, "id_registrazione": "", "tipo": "", "data": g.carico_aperto, "codice": g.codice}
        if tono == "rosso":
            deposito.append({**base, "dettaglio": f"In deposito da {g.giorni_giacenza} giorni (soglia {soglie['giorni_max']})"})
        if g.unita == "misto":
            unita_miste.append({**base, "dettaglio": "Movimenti con unità di misura diverse: la giacenza non è affidabile"})

    sync = [_riga(r, r.sync_errore) for r in records if r.sync_errore]

    return [
        {"key": "orfani", "label": "Scarichi senza carico d'origine", "tone": "danger",
         "desc": "Scarichi e rettifiche la cui catena Rif. Op non arriva a nessun carico valido.", "righe": orfani},
        {"key": "cer", "label": "Catene con codici CER diversi", "tone": "danger",
         "desc": "Il movimento ha un codice diverso dal carico da cui proviene.", "righe": cer_misti},
        {"key": "saldo", "label": "Saldo del deposito sotto zero", "tone": "danger",
         "desc": "In ordine di data, uno scarico porta fuori più di quanto era stato caricato.", "righe": _saldi_negativi(records)},
        {"key": "date", "label": "Date incoerenti", "tone": "warning",
         "desc": "Il movimento è datato prima del movimento a cui si collega.", "righe": date_errate},
        {"key": "duplicati", "label": "Numeri di registrazione doppi", "tone": "warning",
         "desc": "Lo stesso numero su più movimenti (escluse le coppie R+M dello stesso giorno).", "righe": _duplicati()},
        {"key": "quarta_copia", "label": f"Quarta copia FIR oltre {GIORNI_QUARTA_COPIA} giorni", "tone": "warning",
         "desc": "Scarichi originali senza scarico effettivo: la quarta copia del formulario non risulta rientrata.",
         "righe": _quarte_copie(records, oggi)},
        {"key": "tardive", "label": f"Annotazioni oltre {GIORNI_LAVORATIVI_ANNOTAZIONE} giorni lavorativi", "tone": "warning",
         "desc": "Movimenti scritti nel portale troppo tempo dopo la loro data (lo storico importato non è controllato).",
         "righe": _annotazioni_tardive(records)},
        {"key": "deposito", "label": "Deposito temporaneo oltre soglia", "tone": "danger",
         "desc": "Codici con un carico ancora in deposito oltre la soglia in giorni.", "righe": deposito},
        {"key": "unita", "label": "Unità di misura miste", "tone": "info",
         "desc": "Lo stesso codice è registrato con unità diverse (per esempio kg e litri).", "righe": unita_miste},
        {"key": "sync", "label": "Copia SharePoint non allineata", "tone": "info",
         "desc": "Movimenti salvati nel portale ma non arrivati alla lista SharePoint: «rentri_sync_riprova» li reinvia.",
         "righe": sync},
    ]


def conteggi(sezioni: list[dict] | None = None) -> dict[str, int]:
    sezioni = verifica_registro() if sezioni is None else sezioni
    return {s["key"]: len(s["righe"]) for s in sezioni}


def verifica_csv(sezioni: list[dict]):
    from django.http import HttpResponse

    from core.csv_export import safe_csv_writer

    oggi = timezone.localdate()
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="rentri_verifica_{oggi:%Y%m%d}.csv"'
    response.write("﻿")
    writer = safe_csv_writer(response, delimiter=";")
    writer.writerow(["Controllo", "ID Registrazione", "Tipo", "Data", "Codice EER", "Dettaglio"])
    for s in sezioni:
        for r in s["righe"]:
            writer.writerow([
                s["label"], r["id_registrazione"], r["tipo"],
                r["data"].strftime("%d/%m/%Y") if r["data"] else "", r["codice"], r["dettaglio"],
            ])
    return response
