"""Modelli di report predefiniti, pronti all'uso e modificabili.

Usati sia dalla data-migration (con i modelli storici ``apps.get_model``) sia dal
pulsante «Ripristina predefiniti»: un modello predefinito si ricrea solo se il
suo ``codice_sistema`` non esiste piu', le modifiche dell'utente non vengono
mai sovrascritte.
"""
from __future__ import annotations

_FIRME = {"tipo": "FIRME", "titolo": "Approvazione del documento"}

MODELLI = [
    {
        "codice_sistema": "personale_cliente",
        "nome": "Qualifica del personale per cliente",
        "descrizione": "Elenco del personale impiegato con qualifiche, abilitazioni e formazione: la richiesta tipica dei clienti.",
        "titolo_documento": "Qualifica del personale impiegato",
        "sottotitolo": "Evidenza di competenza del personale",
        "destinatario": "",
        "norme": ["ISO 9001", "EN 9100"],
        "riservatezza": "DATI_PERSONALI",
        "periodo_tipo": "ULTIMI_12_MESI",
        "blocchi": [
            {"tipo": "TESTO", "titolo": "Premessa", "testo": (
                "Spett.le {{destinatario}},\n\n"
                "con il presente documento trasmettiamo l'evidenza della competenza del personale "
                "({{n_persone}} persone) alla data del {{oggi}}, come previsto dai requisiti "
                "di sistema per la gestione delle competenze (ISO 9001 / EN 9100 §7.2).\n\n"
                "I dati provengono dall'anagrafica del personale e dallo scadenzario della formazione; "
                "le qualifiche riportate sono quelle in corso di validità o in scadenza.")},
            {"tipo": "SEZIONE", "sezione": "personale_elenco",
             "opzioni": {"colonne": ["nominativo", "matricola", "reparto", "mansione", "assunzione"]}},
            {"tipo": "SEZIONE", "sezione": "personale_qualifiche"},
            {"tipo": "SEZIONE", "sezione": "personale_formazione", "opzioni": {"mostra_note": False}},
            {"tipo": "TESTO", "titolo": "Trattamento dei dati", "testo": (
                "Il documento contiene dati personali comunicati al solo fine di dimostrare la qualifica "
                "del personale impiegato nella commessa. Non è consentita la diffusione a terzi; "
                "i dati vanno conservati per il tempo strettamente necessario (Reg. UE 2016/679).")},
            _FIRME,
        ],
    },
    {
        "codice_sistema": "organico_indicatori",
        "nome": "Organico e indicatori del personale",
        "descrizione": "Fotografia dell'organico con turnover, movimenti e formazione erogata nel periodo.",
        "titolo_documento": "Organico e indicatori del personale",
        "sottotitolo": "Periodo {{periodo}}",
        "norme": ["ISO 9001", "EN 9100"],
        "riservatezza": "INTERNO",
        "periodo_tipo": "ANNO_PRECEDENTE",
        "blocchi": [
            {"tipo": "TESTO", "titolo": "Scopo", "testo": (
                "Il documento riepiloga le risorse umane disponibili (ISO 9001 §7.1.2) e i principali "
                "indicatori del periodo {{periodo}}, come dato di ingresso al riesame della direzione.")},
            {"tipo": "SEZIONE", "sezione": "organico_indicatori"},
            {"tipo": "SEZIONE", "sezione": "organico_movimenti"},
            {"tipo": "SEZIONE", "sezione": "formazione_erogata", "opzioni": {"mostra_tabella": False}},
            {"tipo": "TESTO", "titolo": "Commento della direzione", "testo": (
                "## Andamento\n- Inserire qui la valutazione dell'andamento dell'organico.\n\n"
                "## Azioni\n- Inserire eventuali azioni (inserimenti, piani di formazione, successioni).")},
            _FIRME,
        ],
    },
    {
        "codice_sistema": "sicurezza_45001",
        "nome": "Salute e sicurezza – ISO 45001",
        "descrizione": "Formazione sicurezza, sorveglianza sanitaria (solo validità), DPI ed eventi del periodo.",
        "titolo_documento": "Salute e sicurezza sul lavoro – stato di conformità",
        "sottotitolo": "Periodo {{periodo}}",
        "norme": ["ISO 45001"],
        "riservatezza": "RISERVATO",
        "periodo_tipo": "ULTIMI_12_MESI",
        "blocchi": [
            {"tipo": "TESTO", "titolo": "Scopo", "testo": (
                "Stato della formazione obbligatoria in materia di salute e sicurezza, della sorveglianza "
                "sanitaria e della gestione dei DPI, con gli eventi registrati nel periodo {{periodo}} "
                "(ISO 45001 §7.2, §8.1, §9.1; D.Lgs. 81/2008).")},
            {"tipo": "SEZIONE", "sezione": "sicurezza_formazione"},
            {"tipo": "SEZIONE", "sezione": "sicurezza_sorveglianza"},
            {"tipo": "SEZIONE", "sezione": "rc:dpi"},
            {"tipo": "SEZIONE", "sezione": "rc:eventi-sicurezza"},
            {"tipo": "SEZIONE", "sezione": "rc:scadenziario-legale", "opzioni": {"mostra_tabella": False}},
            _FIRME,
        ],
    },
    {
        "codice_sistema": "parita_genere_pdr125",
        "nome": "Parità di genere – UNI/PdR 125:2022",
        "descrizione": "Indicatori per genere a supporto della certificazione e del piano strategico per la parità.",
        "titolo_documento": "Indicatori di parità di genere",
        "sottotitolo": "UNI/PdR 125:2022 – periodo {{periodo}}",
        "norme": ["UNI/PdR 125:2022"],
        "riservatezza": "RISERVATO",
        "periodo_tipo": "ANNO_PRECEDENTE",
        "blocchi": [
            {"tipo": "TESTO", "titolo": "Premessa", "testo": (
                "Il documento raccoglie gli indicatori quantitativi del sistema di gestione per la parità "
                "di genere (UNI/PdR 125:2022) relativi al periodo {{periodo}}.\n\n"
                "Le aree di valutazione della prassi sono:\n"
                "- Cultura e strategia\n- Governance\n- Processi HR\n"
                "- Opportunità di crescita e inclusione delle donne in azienda\n"
                "- Equità remunerativa per genere\n- Tutela della genitorialità e conciliazione vita-lavoro")},
            {"tipo": "SEZIONE", "sezione": "pdr125_indicatori"},
            {"tipo": "TESTO", "titolo": "Equità remunerativa e genitorialità", "testo": (
                "- Differenziale retributivo per genere a parità di livello: **da inserire**\n"
                "- Fruizione di congedi parentali (donne / uomini): **da inserire**\n"
                "- Misure di conciliazione attive (flessibilità, smart working): **da inserire**")},
            {"tipo": "TESTO", "titolo": "Obiettivi del piano strategico", "testo": (
                "Riportare obiettivi, responsabili e scadenze del piano strategico per la parità di genere "
                "e lo stato di avanzamento rispetto al periodo precedente.")},
            _FIRME,
        ],
    },
]


MODELLI += [
    {
        "codice_sistema": "matrice_commessa",
        "nome": "Matrice competenze per commessa",
        "descrizione": "Griglia persone × qualifiche e abilitazioni ai processi speciali per il personale di una commessa.",
        "titolo_documento": "Matrice delle competenze del personale di commessa",
        "sottotitolo": "Situazione al {{oggi}}",
        "norme": ["ISO 9001", "EN 9100"],
        "riservatezza": "DATI_PERSONALI",
        "periodo_tipo": "ULTIMI_12_MESI",
        "formato_predefinito": "xlsx",
        "blocchi": [
            {"tipo": "TESTO", "titolo": "Premessa", "testo": (
                "Spett.le {{destinatario}},\n\nsi trasmette la matrice delle competenze del personale "
                "({{n_persone}} persone) previsto per la commessa, alla data del {{oggi}}. "
                "Selezionare le persone nel perimetro prima della generazione.")},
            {"tipo": "SEZIONE", "sezione": "matrice_qualifiche"},
            {"tipo": "SEZIONE", "sezione": "abilitazioni_processi", "opzioni": {"mostra_indicatori": False}},
            {"tipo": "SEZIONE", "sezione": "matrice_formazione",
             "opzioni": {"valori": {"solo_sicurezza": True}}},
            _FIRME,
        ],
    },
    {
        "codice_sistema": "scadenzario_mensile",
        "nome": "Scadenzario mensile del personale",
        "descrizione": "Scadenze dei prossimi 90 giorni (qualifiche, formazione, certificazioni), raggruppate per mese.",
        "titolo_documento": "Scadenzario del personale",
        "sottotitolo": "Prossimi 90 giorni dal {{oggi}}",
        "norme": ["ISO 9001", "ISO 45001"],
        "riservatezza": "INTERNO",
        "periodo_tipo": "ULTIMI_12_MESI",
        "blocchi": [
            {"tipo": "SEZIONE", "sezione": "scadenzario_unico",
             "opzioni": {"colonne": ["scadenza", "giorni", "tipo", "nominativo", "reparto", "voce"],
                         "valori": {"raggruppa_per": "mese"}}},
        ],
    },
]


def crea_predefiniti(Modello, Blocco, *, solo_mancanti: bool = True) -> int:
    """Crea i modelli predefiniti mancanti. Ritorna quanti ne ha creati.

    Funziona anche con i modelli storici delle migrazioni: i campi che a quella
    migrazione non esistono ancora vengono ignorati.
    """
    esistenti = set(Modello.objects.exclude(codice_sistema="").values_list("codice_sistema", flat=True))
    nomi_campi = {f.name for f in Modello._meta.get_fields()}
    creati = 0
    for spec in MODELLI:
        if solo_mancanti and spec["codice_sistema"] in esistenti:
            continue
        campi = {k: v for k, v in spec.items() if k != "blocchi" and k in nomi_campi}
        modello = Modello.objects.create(**campi)
        for ordine, b in enumerate(spec["blocchi"], start=1):
            Blocco.objects.create(
                modello=modello, ordine=ordine * 10, tipo=b["tipo"], titolo=b.get("titolo", ""),
                testo=b.get("testo", ""), sezione=b.get("sezione", ""), opzioni=dict(b.get("opzioni") or {}),
            )
        creati += 1
    return creati
