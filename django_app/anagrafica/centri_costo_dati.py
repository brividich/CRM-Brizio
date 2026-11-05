"""Centri di costo e ruoli per reparto: elenco fornito dall'utente il 05/11/2026.

Solo struttura aziendale, nessun dato personale. Il «reparto» dell'elenco è
un'AREA del portale (come nel file MEGA SKILL MATRIX v8), per questo il centro
di costo sta sull'area: un reparto del portale come AGG/MONT ha aree in centri
di costo diversi.

``ELENCO``: (reparto dell'elenco, centro di costo o None se N/A, ruoli).
``ALIAS_AREA``: reparto dell'elenco → area del portale che ha un altro nome.
``NUOVE_AREE``: reparti dell'elenco che nel portale non esistono ancora (o sono
spenti) → reparto del portale che li contiene (None = lo sceglie
l'amministrazione). Nascono vuoti: gli spostamenti delle persone restano una
scelta dell'HR.
"""
from __future__ import annotations

CAR_OMU = ["CAR", "Operatore Macchina Utensile"]
CAR_OMA = ["CAR", "Operatore Manuale"]
CAR_OCQ = ["CAR", "Operatore Controllo Qualità"]

ELENCO = [
    ("AGGIUSTAGGIO", "AGGIUSTAGGIO", CAR_OMA),
    ("ALC", "ALC", CAR_OMU),
    ("CN5", "CN5", CAR_OMU),
    ("CN5GL", "CN5GL", CAR_OMU),
    ("CN5GS", "CN5GS", CAR_OMU),
    ("CNC", "CN4", CAR_OMU),
    ("CND", "CND", CAR_OCQ),
    ("CONTROLLO CMM", "ZEISS", CAR_OCQ),
    ("CONTROLLO TRADIZIONALE", "CONTROLLI TRADIZIONALI", CAR_OCQ),
    ("DIREZIONE", None, ["BDM", "CEO", "RDD"]),
    ("LAVAGGIO", "LOGISTICA", ["CAR", "Operatore Generico"]),
    ("LAVAGGIO CONDOTTI", "AGGIUSTAGGIO", CAR_OMA),
    ("LOGISTICA", "LOGISTICA", ["LOG", "LOGO", "Operatore Logistica", "PRS"]),
    ("MAGAZZINO NORMALERIA", "NORMALERIA", ["CAR", "Operatore Logistica"]),
    ("MARCATURA", "AGGIUSTAGGIO", CAR_OMA),
    ("MASCHERATURA", "MASCHERATURA/VERNICIATURA", CAR_OMA),
    ("MONTAGGIO", "MONTAGGIO", CAR_OMA),
    ("PRESETTING", "PRESETTING", ["CAR", "Operatore Presetting"]),
    ("PROGRAMMAZIONE CMM", "UFFICIO PROGRAMMAZIONE CMM", CAR_OCQ),
    ("PROVA PRESSIONE", "AGGIUSTAGGIO", CAR_OMA),
    ("RETTIFICA", "TRADIZIONALI", CAR_OMU),
    ("SALA TAGLIO", "SALA TAGLIO", ["CAR", "Operatore Generico"]),
    ("TARATURA", "STRUTTURA", CAR_OCQ),
    ("TNCG", "TNCG", CAR_OMU),
    ("TNF", "TNF", CAR_OMU),
    ("TORNI", "TORNI", CAR_OMU),
    ("TRADIZIONALE", "TRADIZIONALI", CAR_OMU),
    ("UFFICIO ACQUISTI", "STRUTTURA", ["PM", "PRM"]),
    ("UFFICIO AMMINISTRAZIONE", "STRUTTURA", ["ACA", "ACM", "ACO"]),
    ("UFFICIO COMMERCIALE", "STRUTTURA", ["BOF", "COS", "SAM", "SAO"]),
    ("UFFICIO FAI", "FAI", ["FAI", "FAIO"]),
    ("UFFICIO HSE", "STRUTTURA", ["ESM", "ESO", "Operatore Generico"]),
    ("UFFICIO IT", "STRUTTURA", ["ITA", "ITM"]),
    ("UFFICIO OPERATIONS", "OPERATIONS", ["OPA", "OPM"]),
    ("UFFICIO RISORSE UMANE", "STRUTTURA", ["HRM", "HRO"]),
    ("UFFICIO SISTEMA QUALITÀ", "STRUTTURA", ["DM", "MSA", "MSM", "MSO", "PCO"]),
    ("UFFICIO TECNICO (CAM)", "UFFICIO PROGRAMMAZIONE CAM", ["AIN", "CAMM", "IN2", "MIN2"]),
    ("UFFICIO TECNICO (ING)", "INGEGNERIA", ["EM", "IN1", "MIN1"]),
    ("VERNICIATURA", "MASCHERATURA/VERNICIATURA", CAR_OMA),
]

ALIAS_AREA = {
    "UFFICIO ACQUISTI": "ACQUISTI",
    "UFFICIO AMMINISTRAZIONE": "AMMINISTRAZIONE",
    "UFFICIO COMMERCIALE": "COMMERCIALE",
    "UFFICIO HSE": "HSE",
    "UFFICIO IT": "IT",
    "UFFICIO OPERATIONS": "OPERATIONS",
    "UFFICIO RISORSE UMANE": "RISORSE UMANE",
    "UFFICIO SISTEMA QUALITÀ": "QUALITA",
}

NUOVE_AREE = {
    "CN5GL": "CN5G",
    "CN5GS": "CN5G",
    "CND": "CONTROLLO",
    "CONTROLLO CMM": "CONTROLLO",
    "CONTROLLO TRADIZIONALE": "CONTROLLO",
    "MAGAZZINO NORMALERIA": "LOGISTICA",
    "PROGRAMMAZIONE CMM": "CONTROLLO",
    "TARATURA": "CONTROLLO",
    "TNCG": None,
    "UFFICIO FAI": "UT",
    "UFFICIO TECNICO (CAM)": "UT",
    "UFFICIO TECNICO (ING)": "UT",
}


def _chiave(testo) -> str:
    return " ".join((testo or "").split()).upper()


def assicura_cam_manager(RuoloOperativo, AmbitoRuolo, AreaAziendale):
    """Ruolo CAMM «CAM Manager» nel reparto UFFICIO TECNICO (CAM), se quel reparto esiste."""
    area = AreaAziendale.objects.filter(nome__iexact="UFFICIO TECNICO (CAM)").first()
    if area is None:
        return None
    ruolo = RuoloOperativo.objects.filter(sigla__iexact="CAMM").first()
    if ruolo is None:
        ruolo = RuoloOperativo.objects.filter(nome__iexact="CAM Manager").first()
    if ruolo is None:
        ruolo = RuoloOperativo.objects.create(
            nome="CAM Manager", sigla="CAMM", classe="INDIRETTO",
            ambito=AmbitoRuolo.objects.filter(nome__iexact="Produttivo").first(),
        )
    area.ruoli_reparto.add(ruolo)
    return ruolo


def carica_elenco(CentroDiCosto, AreaAziendale, Reparto, RuoloOperativo) -> dict:
    """Carica l'elenco senza toccare ciò che è già deciso (si può rilanciare).

    Prende i modelli come argomenti per funzionare anche dentro una migrazione.
    Non inventa ruoli: quelli fuori catalogo tornano in ``ruoli_mancanti``.
    """
    centri = {_chiave(c.nome): c for c in CentroDiCosto.objects.all()}
    aree = {_chiave(a.nome): a for a in AreaAziendale.objects.all()}
    reparti = {_chiave(r.nome): r for r in Reparto.objects.all()}
    attivi = list(RuoloOperativo.objects.filter(is_active=True))
    ruoli = {_chiave(r.nome): r for r in attivi}
    ruoli.update({_chiave(r.sigla): r for r in attivi if r.sigla})  # la sigla vince sul nome

    esito = {"centri": 0, "aree_create": [], "aree_riattivate": [], "collegate": 0, "ruoli_mancanti": []}
    for nome_reparto, nome_centro, nomi_ruoli in ELENCO:
        centro = None
        if nome_centro:
            centro = centri.get(_chiave(nome_centro))
            if centro is None:
                centro = CentroDiCosto.objects.create(nome=nome_centro)
                centri[_chiave(nome_centro)] = centro
                esito["centri"] += 1

        # Prima il nome che l'area ha nel portale, poi quello dell'elenco (area già creata da un giro prima).
        area = aree.get(_chiave(ALIAS_AREA.get(nome_reparto, nome_reparto))) or aree.get(_chiave(nome_reparto))
        if area is None:
            padre = NUOVE_AREE.get(nome_reparto)
            area = AreaAziendale.objects.create(
                nome=nome_reparto, reparto=reparti.get(_chiave(padre)) if padre else None,
            )
            aree[_chiave(nome_reparto)] = area
            esito["aree_create"].append(nome_reparto)
        elif not area.is_active and nome_reparto in NUOVE_AREE:
            area.is_active = True
            area.save(update_fields=["is_active"])
            esito["aree_riattivate"].append(area.nome)

        if centro is not None and area.centro_di_costo_id is None:
            area.centro_di_costo = centro
            area.save(update_fields=["centro_di_costo"])
            esito["collegate"] += 1

        trovati = []
        for nome_ruolo in nomi_ruoli:
            ruolo = ruoli.get(_chiave(nome_ruolo))
            if ruolo is not None:
                trovati.append(ruolo)
            elif nome_ruolo not in esito["ruoli_mancanti"]:
                esito["ruoli_mancanti"].append(nome_ruolo)
        if trovati:
            area.ruoli_reparto.add(*trovati)
    return esito
