"""Costanti di dominio per l'app gestione_specifiche.

Centralizza codici stato (macchina a stati §6), choices dei modelli (§5) e i
modi di approvazione del documento CN (decisione F0 #2). Importati sia dai
modelli sia dalla macchina a stati per evitare stringhe magiche sparse.
"""
from __future__ import annotations

# --- Stati Specifica (FSM §6) -------------------------------------------------
STATO_BOZZA = "bozza"                    # S1
STATO_FLOW_DOWN = "flow_down"            # S2
STATO_IN_VALIDITA = "in_validita"        # S3
STATO_SUPERATO = "superato"              # S4
STATO_SOSPESO = "sospeso"                # S5
STATO_ANNULLATO = "annullato"            # S6
STATO_DUPLICATO = "duplicato"            # S7
STATO_RESPINTO = "respinto"              # S8
STATO_ERRORE_TECNICO = "errore_tecnico"  # S9

STATO_CHOICES = [
    (STATO_BOZZA, "S1 · Bozza"),
    (STATO_FLOW_DOWN, "S2 · Flow-down"),
    (STATO_IN_VALIDITA, "S3 · In validità"),
    (STATO_SUPERATO, "S4 · Superato"),
    (STATO_SOSPESO, "S5 · Sospeso"),
    (STATO_ANNULLATO, "S6 · Annullato"),
    (STATO_DUPLICATO, "S7 · Duplicato"),
    (STATO_RESPINTO, "S8 · Respinto"),
    (STATO_ERRORE_TECNICO, "S9 · Errore tecnico"),
]

# Stati "attivi" (mostrati di default nell'elenco) vs "storici/terminali".
STATI_ATTIVI = {STATO_BOZZA, STATO_FLOW_DOWN, STATO_IN_VALIDITA, STATO_SOSPESO}
STATI_TERMINALI = {STATO_SUPERATO, STATO_ANNULLATO, STATO_DUPLICATO, STATO_RESPINTO}

# --- Tipo / Fonte Specifica ---------------------------------------------------
TIPO_SPECIFICA = "specifica"
TIPO_COMUNICAZIONE = "comunicazione"
TIPO_PIANO_QUALITA = "piano_qualita"
TIPO_CHOICES = [
    (TIPO_SPECIFICA, "Specifica tecnica"),
    (TIPO_COMUNICAZIONE, "Comunicazione"),
    (TIPO_PIANO_QUALITA, "Piano di qualità"),
]

FONTE_CLIENTE = "cliente"
FONTE_GENERICA = "generica"
FONTE_CHOICES = [
    (FONTE_CLIENTE, "Cliente"),
    (FONTE_GENERICA, "Generica"),
]

# --- Esito MOD.133 ------------------------------------------------------------
ESITO_APPROVATO = "approvato"
ESITO_RESPINTO = "respinto"
ESITO_NON_APPLICABILE = "non_applicabile"
ESITO_CHOICES = [
    (ESITO_APPROVATO, "Approvato"),
    (ESITO_RESPINTO, "Respinto"),
    (ESITO_NON_APPLICABILE, "Non applicabile"),
]

# --- Azione OFI ---------------------------------------------------------------
# Modi di approvazione documento CN (decisione F0 #2).
APPROV_MOD133 = "mod133_approver"
APPROV_CAR_FLOW = "car_flow"
APPROV_RDD = "rdd_dedicato"
MODO_APPROVAZIONE_CHOICES = [
    (APPROV_MOD133, "Approvatore MOD.133"),
    (APPROV_CAR_FLOW, "Flusso CAR"),
    (APPROV_RDD, "RDD dedicato"),
]

AZIONE_OFI_BOZZA = "bozza"
AZIONE_OFI_IN_APPROVAZIONE = "in_approvazione"
AZIONE_OFI_APPROVATA = "approvata"
AZIONE_OFI_RESPINTA = "respinta"
AZIONE_OFI_STATO_CHOICES = [
    (AZIONE_OFI_BOZZA, "Bozza"),
    (AZIONE_OFI_IN_APPROVAZIONE, "In approvazione"),
    (AZIONE_OFI_APPROVATA, "Approvata"),
    (AZIONE_OFI_RESPINTA, "Respinta"),
]

# --- Distribuzione ------------------------------------------------------------
CANALE_EMAIL = "email"
CANALE_NOTIFICA = "notifica"
CANALE_CARTACEO = "cartaceo"
CANALE_CHOICES = [
    (CANALE_EMAIL, "Email"),
    (CANALE_NOTIFICA, "Notifica in-app"),
    (CANALE_CARTACEO, "Cartaceo"),
]
