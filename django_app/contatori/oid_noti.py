"""Nomi degli OID noti (MIB standard e MIB pubbliche dei produttori).

Servono a dare un nome leggibile alle righe di «Verifica OID» senza AI. Non
rendono valido un OID: nel profilo entra solo cio' che l'apparato ha risposto.
Ogni voce: (nome, unita, fattore, aggregazione, etichette).
"""

OPER_STATUS = "1=Su, 2=Giù, 3=Test, 4=Sconosciuto, 5=Dormiente, 6=Assente, 7=Livello inferiore giù"
HP_SENSORE = "1=Sconosciuto, 2=Guasto, 3=Attenzione, 4=Ok, 5=Assente"

OID_NOTI = {
    # MIB-II / HOST-RESOURCES-MIB
    "1.3.6.1.2.1.1.1.0": ("Descrizione sistema", "", "1", "PRIMO", ""),
    "1.3.6.1.2.1.1.3.0": ("Uptime servizio SNMP", "s", "1", "PRIMO", ""),
    "1.3.6.1.2.1.1.5.0": ("Nome host", "", "1", "PRIMO", ""),
    "1.3.6.1.2.1.25.1.1.0": ("Uptime sistema", "s", "1", "PRIMO", ""),
    "1.3.6.1.2.1.25.3.3.1.2": ("Carico CPU medio sui core", "%", "1", "MEDIA", ""),
    "1.3.6.1.2.1.25.2.3.1.1": ("Memorie/dischi: indice", "", "1", "PRIMO", ""),
    "1.3.6.1.2.1.25.2.3.1.2": ("Memorie/dischi: tipo", "", "1", "PRIMO", ""),
    "1.3.6.1.2.1.25.2.3.1.3": ("Memorie/dischi: descrizione", "", "1", "PRIMO", ""),
    "1.3.6.1.2.1.25.2.3.1.4": ("Memorie/dischi: unità di allocazione", "byte", "1", "PRIMO", ""),
    "1.3.6.1.2.1.25.2.3.1.5": ("Memorie/dischi: dimensione (in unità)", "", "1", "MASSIMO", ""),
    "1.3.6.1.2.1.25.2.3.1.6": ("Memorie/dischi: usato (in unità)", "", "1", "MASSIMO", ""),
    # IF-MIB
    "1.3.6.1.2.1.2.2.1.8": ("Stato porte", "", "1", "PRIMO", OPER_STATUS),
    "1.3.6.1.2.1.2.2.1.14": ("Errori in ingresso (tutte le porte)", "errori", "1", "SOMMA", ""),
    "1.3.6.1.2.1.2.2.1.20": ("Errori in uscita (tutte le porte)", "errori", "1", "SOMMA", ""),
    "1.3.6.1.2.1.31.1.1.1.1": ("Nome porta", "", "1", "PRIMO", ""),
    "1.3.6.1.2.1.31.1.1.1.6": ("Traffico ricevuto totale (64 bit)", "byte", "1", "SOMMA", ""),
    "1.3.6.1.2.1.31.1.1.1.10": ("Traffico trasmesso totale (64 bit)", "byte", "1", "SOMMA", ""),
    # POWER-ETHERNET-MIB
    "1.3.6.1.2.1.105.1.3.1.1.2": ("PoE potenza disponibile", "W", "1", "SOMMA", ""),
    "1.3.6.1.2.1.105.1.3.1.1.3": ("PoE stato alimentatore", "", "1", "MASSIMO", "1=Acceso, 2=Spento, 3=Guasto"),
    "1.3.6.1.2.1.105.1.3.1.1.4": ("PoE consumo", "W", "1", "SOMMA", ""),
    # UPS-MIB
    "1.3.6.1.2.1.33.1.2.1.0": ("UPS stato batteria", "", "1", "PRIMO", "1=Sconosciuto, 2=Normale, 3=Bassa, 4=Esaurita"),
    "1.3.6.1.2.1.33.1.2.3.0": ("UPS autonomia stimata", "min", "1", "PRIMO", ""),
    "1.3.6.1.2.1.33.1.2.4.0": ("UPS carica residua", "%", "1", "PRIMO", ""),
    # UCD-SNMP-MIB memoria (valori in kB)
    "1.3.6.1.4.1.2021.4.1.0": ("Memoria: indice", "", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.2.0": ("Memoria: nome swap", "", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.3.0": ("Swap totale", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.4.0": ("Swap disponibile", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.5.0": ("RAM totale", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.6.0": ("RAM libera (esclusa cache)", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.11.0": ("Memoria libera totale (RAM + swap)", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.12.0": ("Swap minimo", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.13.0": ("Memoria condivisa", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.14.0": ("Memoria buffer", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.15.0": ("Memoria cache", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.18.0": ("Swap totale (64 bit)", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.19.0": ("Swap disponibile (64 bit)", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.20.0": ("RAM totale (64 bit)", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.21.0": ("RAM libera (64 bit)", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.22.0": ("Memoria libera totale (64 bit)", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.23.0": ("Swap minimo (64 bit)", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.24.0": ("Memoria condivisa (64 bit)", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.25.0": ("Memoria buffer (64 bit)", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.26.0": ("Memoria cache (64 bit)", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.27.0": ("RAM disponibile (con cache)", "kB", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.4.100.0": ("Allarme swap", "", "1", "PRIMO", "0=Ok, 1=Swap in esaurimento"),
    "1.3.6.1.4.1.2021.4.101.0": ("Messaggio allarme swap", "", "1", "PRIMO", ""),
    # UCD-SNMP-MIB carico e CPU
    "1.3.6.1.4.1.2021.10.1.3": ("Carico medio (1/5/15 min), massimo", "", "1", "MASSIMO", ""),
    "1.3.6.1.4.1.2021.11.1.0": ("Statistiche: indice", "", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.2.0": ("Statistiche: nome", "", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.3.0": ("Swap in", "kB/s", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.4.0": ("Swap out", "kB/s", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.5.0": ("I/O scritti (deprecato)", "blocchi/s", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.6.0": ("I/O letti (deprecato)", "blocchi/s", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.7.0": ("Interrupt", "/s", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.8.0": ("Cambi di contesto", "/s", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.9.0": ("CPU utente", "%", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.10.0": ("CPU sistema", "%", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.11.0": ("CPU inattiva", "%", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.50.0": ("CPU contatore utente (grezzo)", "tick", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.51.0": ("CPU contatore nice (grezzo)", "tick", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.52.0": ("CPU contatore sistema (grezzo)", "tick", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.53.0": ("CPU contatore inattività (grezzo)", "tick", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.54.0": ("CPU contatore attesa I/O (grezzo)", "tick", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.55.0": ("CPU contatore kernel (grezzo)", "tick", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.56.0": ("CPU contatore interrupt (grezzo)", "tick", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.57.0": ("I/O blocchi scritti (grezzo)", "blocchi", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.58.0": ("I/O blocchi letti (grezzo)", "blocchi", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.59.0": ("Interrupt totali (grezzo)", "", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.60.0": ("Cambi di contesto totali (grezzo)", "", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.61.0": ("CPU contatore softirq (grezzo)", "tick", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.62.0": ("Swap in totali (grezzo)", "pagine", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.63.0": ("Swap out totali (grezzo)", "pagine", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.64.0": ("CPU contatore steal (grezzo)", "tick", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.65.0": ("CPU contatore guest (grezzo)", "tick", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.66.0": ("CPU contatore guest nice (grezzo)", "tick", "1", "PRIMO", ""),
    "1.3.6.1.4.1.2021.11.67.0": ("Numero di CPU", "", "1", "PRIMO", ""),
    # WatchGuard Fireware (WATCHGUARD-SYSTEM-STATISTICS-MIB)
    "1.3.6.1.4.1.3097.6.3.1.0": ("Versione Fireware", "", "1", "PRIMO", ""),
    "1.3.6.1.4.1.3097.6.3.8.0": ("Byte inviati totali", "byte", "1", "PRIMO", ""),
    "1.3.6.1.4.1.3097.6.3.9.0": ("Byte ricevuti totali", "byte", "1", "PRIMO", ""),
    "1.3.6.1.4.1.3097.6.3.10.0": ("Pacchetti inviati totali", "pacchetti", "1", "PRIMO", ""),
    "1.3.6.1.4.1.3097.6.3.11.0": ("Pacchetti ricevuti totali", "pacchetti", "1", "PRIMO", ""),
    "1.3.6.1.4.1.3097.6.3.77.0": ("CPU media 1 minuto", "%", "0.01", "PRIMO", ""),
    "1.3.6.1.4.1.3097.6.3.78.0": ("CPU media 5 minuti", "%", "0.01", "PRIMO", ""),
    "1.3.6.1.4.1.3097.6.3.79.0": ("CPU media 15 minuti", "%", "0.01", "PRIMO", ""),
    "1.3.6.1.4.1.3097.6.3.80.0": ("Connessioni attive", "connessioni", "1", "PRIMO", ""),
    # HPE Aruba / ProCurve (ArubaOS-Switch)
    "1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0": ("CPU", "%", "1", "PRIMO", ""),
    "1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.5": ("Memoria totale", "byte", "1", "SOMMA", ""),
    "1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.6": ("Memoria libera", "byte", "1", "SOMMA", ""),
    "1.3.6.1.4.1.11.2.14.11.1.2.6.1.4": ("Sensori: stato peggiore", "", "1", "MINIMO", HP_SENSORE),
    "1.3.6.1.4.1.11.2.14.11.1.2.6.1.7": ("Sensori: descrizione", "", "1", "PRIMO", ""),
    # Cisco Small Business (SG/CBS)
    "1.3.6.1.4.1.9.6.1.101.1.7.0": ("CPU ultimi 5 secondi", "%", "1", "PRIMO", ""),
    "1.3.6.1.4.1.9.6.1.101.1.8.0": ("CPU ultimo minuto", "%", "1", "PRIMO", ""),
    "1.3.6.1.4.1.9.6.1.101.1.9.0": ("CPU ultimi 5 minuti", "%", "1", "PRIMO", ""),
}

CAMPI = ("nome", "unita", "fattore", "aggregazione", "etichette")

# Soglie (avviso sopra, critico sopra) sul valore gia' moltiplicato per il fattore.
SOGLIE = {
    "1.3.6.1.2.1.25.3.3.1.2": ("85", "95"),
    "1.3.6.1.4.1.3097.6.3.77.0": ("80", "95"),
    "1.3.6.1.4.1.3097.6.3.78.0": ("80", "95"),
    "1.3.6.1.4.1.3097.6.3.79.0": ("80", "95"),
    "1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0": ("85", "95"),
    "1.3.6.1.4.1.9.6.1.101.1.8.0": ("85", "95"),
    "1.3.6.1.4.1.9.6.1.101.1.9.0": ("85", "95"),
    "1.3.6.1.4.1.2021.4.100.0": ("", "0"),
}


def proposta_nota(oid: str, modalita: str) -> dict | None:
    """Proposta dal catalogo per un OID verificato, o None se sconosciuto."""
    voce = OID_NOTI.get(oid)
    suffisso = ""
    if voce is None and modalita == "GET":
        genitore, _, indice = oid.rpartition(".")
        voce = OID_NOTI.get(genitore)
        if voce is not None:
            suffisso = f" (riga {indice})"
    if voce is None:
        return None
    proposta = dict(zip(CAMPI, voce))
    proposta["nome"] = (proposta["nome"] + suffisso)[:100]
    if modalita == "GET":
        proposta["aggregazione"] = "PRIMO"
    avviso, critico = SOGLIE.get(oid, ("", ""))
    proposta.update({"avviso_sopra": avviso, "critico_sopra": critico,
                     "motivo": "Nome dal catalogo MIB", "fonte": "catalogo"})
    return proposta
