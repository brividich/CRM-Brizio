"""Conversione una tantum dei nominativi salvati in Anomalie da «Nome Cognome» al
formato unico del portale «COGNOME NOME» (``core.naming.nome_completo``), 24/11/2026.

Si converte solo un nominativo che corrisponde a UNA persona dell'anagrafica
(stesse parole in qualunque ordine, ``core.naming.chiave_persona``): un testo
libero che non è una persona (o che vale per due omonimi) resta com'è. I
confronti del modulo non dipendono più dall'ordine, quindi un valore non
convertito continua a funzionare.

Usato dalla migrazione ``anomalie 0034`` e dai test; non tocca i dati del
gestionale (``ordini_produzione``), che arrivano da fuori.
"""

from __future__ import annotations

from core import naming

#: Chiavi del JSON di configurazione che contengono elenchi di nominativi.
CHIAVI_PERSONE = frozenset({"referenti_rdc", "autorizzati_modifica", "extra", "esclusi", "persone"})


def mappa_da_righe(righe) -> dict[str, str]:
    """``{chiave_persona: "COGNOME NOME"}`` da righe ``(nome, cognome)``; omonimi esclusi."""
    mappa: dict[str, str] = {}
    doppie: set[str] = set()
    for nome, cognome in righe:
        etichetta = naming.nome_completo(nome, cognome)
        if not etichetta:
            continue
        chiave = naming.chiave_persona(etichetta)
        if chiave in mappa and mappa[chiave] != etichetta:
            doppie.add(chiave)
        mappa.setdefault(chiave, etichetta)
    for chiave in doppie:
        mappa.pop(chiave, None)
    return mappa


def converti_nome(valore, mappa: dict[str, str]):
    """Il nominativo nel formato COGNOME NOME se è una persona nota, altrimenti invariato."""
    if not isinstance(valore, str) or not valore.strip():
        return valore
    return mappa.get(naming.chiave_persona(valore), valore)


def converti_config(dati, mappa: dict[str, str], chiave: str = ""):
    """Copia del JSON di configurazione con gli elenchi di persone convertiti."""
    if isinstance(dati, dict):
        return {k: converti_config(v, mappa, k) for k, v in dati.items()}
    if isinstance(dati, list):
        if chiave in CHIAVI_PERSONE:
            out, visti = [], set()
            for v in dati:
                nuovo = converti_nome(v, mappa)
                k = naming.chiave_persona(nuovo) if isinstance(nuovo, str) else repr(nuovo)
                if k in visti:
                    continue  # «Mario Rossi» e «ROSSI MARIO» erano la stessa persona
                visti.add(k)
                out.append(nuovo)
            return out
        return [converti_config(v, mappa, chiave) for v in dati]
    return dati


def converti_elenco_testo(testo: str, mappa: dict[str, str]) -> str:
    """``car_segnalati``: nominativi separati da «; »."""
    if not testo:
        return testo
    voci = [v.strip() for v in str(testo).replace("\n", ";").split(";") if v.strip()]
    out, visti = [], set()
    for v in voci:
        nuovo = converti_nome(v, mappa)
        k = naming.chiave_persona(nuovo)
        if k in visti:
            continue
        visti.add(k)
        out.append(nuovo)
    return "; ".join(out)[:500]
