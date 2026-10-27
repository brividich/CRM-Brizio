"""Checklist di audit per norma (fase 4): EN 9100 Folder B, ISO 45001, UNI/PdR 125.

Ogni norma ha una sola revisione attiva: è quella caricata all'avvio degli audit che hanno la norma
spuntata. Una revisione già usata in un audit non si modifica: se ne apre una nuova (copia).

Per ISO 45001 e UNI/PdR 125 l'azienda non ha un modulo di checklist: il portale propone una bozza
di base, con domande guida scritte per il portale (non il testo delle norme) e i riferimenti alle
procedure MT CN. La bozza nasce inattiva: RSGI la verifica, la completa e la attiva.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from ..models import AuditEsito, AuditSezioneCar, ChecklistDomanda, ChecklistModello, ChecklistSezione


class ChecklistNonModificabile(Exception):
    pass


NORME = {
    ChecklistModello.CODICE_EN9100_FOLDER_B: {
        "flag": "en9100", "norma": "UNI EN 9100:2018", "titolo": "Folder B - Audit di sistema EN 9100:2018",
        "breve": "EN 9100",
    },
    ChecklistModello.CODICE_ISO45001: {
        "flag": "iso45001", "norma": "UNI ISO 45001:2018", "titolo": "Audit di sistema ISO 45001:2018",
        "breve": "ISO 45001",
    },
    ChecklistModello.CODICE_PDR125: {
        "flag": "pdr125", "norma": "UNI/PdR 125:2022", "titolo": "Audit di sistema UNI/PdR 125:2022",
        "breve": "UNI/PdR 125",
    },
}

# Bozze di base: (codice sezione, titolo, criteri, [(punti, domanda guida)]).
BOZZA_ISO45001 = [
    ("§4", "Contesto dell'organizzazione", "Manuale SGI · MT CN 453 · MOD.147", [
        ("4.1", "Sono individuati e riesaminati i fattori interni ed esterni che incidono sulla salute e sicurezza sul lavoro?"),
        ("4.2", "Sono individuati bisogni e aspettative dei lavoratori e delle altre parti interessate, compresi i requisiti legali?"),
        ("4.3 4.4", "Il campo di applicazione è documentato e i processi del sistema sono definiti con le loro interazioni?"),
    ]),
    ("§5", "Leadership e partecipazione dei lavoratori", "MT CN 452 · organigramma della sicurezza", [
        ("5.1", "La direzione dimostra leadership e si assume la responsabilità della prevenzione di infortuni e malattie professionali?"),
        ("5.2", "La politica SSL è documentata, comunicata e disponibile, con l'impegno a eliminare i pericoli e a consultare i lavoratori?"),
        ("5.3", "Ruoli, responsabilità e autorità per la sicurezza (nomine D.Lgs. 81/08) sono assegnati e comunicati?"),
        ("5.4", "Consultazione e partecipazione dei lavoratori e del RLS: modalità, tempi ed evidenze (verbali, riunione periodica)?"),
    ]),
    ("§6", "Pianificazione", "DVR · MT CN 453 · MOD.147", [
        ("6.1.1", "Rischi e opportunità del sistema sono determinati e le azioni conseguenti pianificate?"),
        ("6.1.2", "Pericoli e rischi sono valutati e aggiornati (DVR), anche per attività non routinarie, appaltatori e visitatori?"),
        ("6.1.3", "I requisiti legali e gli altri requisiti sono individuati, accessibili e aggiornati nel registro delle prescrizioni?"),
        ("6.1.4", "Le azioni pianificate su rischi, opportunità e requisiti legali sono attuate e ne è verificata l'efficacia?"),
        ("6.2", "Gli obiettivi SSL sono misurabili, con piano (chi, cosa, risorse, scadenze) e monitoraggio?"),
    ]),
    ("§7", "Supporto", "MT CN 451 · MT CN 455 · registro formazione", [
        ("7.1 7.2", "Le risorse sono adeguate e la formazione e l'addestramento dei lavoratori e dei preposti sono conformi e registrati?"),
        ("7.3", "I lavoratori conoscono politica, rischi, procedure e la possibilità di allontanarsi da situazioni di pericolo grave?"),
        ("7.4", "La comunicazione interna ed esterna sulla sicurezza è pianificata e registrata?"),
        ("7.5", "Le informazioni documentate sono controllate (revisione, distribuzione, conservazione)?"),
    ]),
    ("§8", "Attività operative", "MT CN 451 · MT CN 454 · MT CN 455 · piano di emergenza", [
        ("8.1.1", "I controlli operativi sono applicati (istruzioni, DPI, manutenzione di macchine e attrezzature)?"),
        ("8.1.2", "Si segue la gerarchia delle misure: eliminazione e riduzione dei rischi prima del ricorso ai DPI?"),
        ("8.1.3", "Nuovi processi, macchine, sostanze o modifiche di layout sono valutati prima dell'introduzione?"),
        ("8.1.4", "Acquisti, appaltatori (DUVRI, art. 26 D.Lgs. 81/08) e processi affidati all'esterno sono controllati?"),
        ("8.2", "Emergenze: piano, squadre, prove di evacuazione e primo soccorso sono attuati e registrati?"),
    ]),
    ("§9", "Valutazione delle prestazioni", "Indicatori SSL · sorveglianza sanitaria · MT CN 12", [
        ("9.1.1", "Prestazioni monitorate e misurate (infortuni, quasi incidenti, sorveglianza sanitaria, misure ambientali) con strumenti tarati?"),
        ("9.1.2", "La valutazione periodica della conformità ai requisiti legali è registrata?"),
        ("9.2", "Gli audit interni sono pianificati ed eseguiti e i risultati comunicati ai lavoratori e al RLS?"),
        ("9.3", "Il riesame della direzione tratta gli elementi in ingresso richiesti e ne registra le decisioni?"),
    ]),
    ("§10", "Miglioramento", "MT CN 11 · Registro OFI MOD.174", [
        ("10.2", "Incidenti e non conformità sono indagati, con cause e azioni correttive, coinvolgendo i lavoratori?"),
        ("10.3", "Il miglioramento continuo è dimostrato (obiettivi raggiunti, andamento degli indicatori)?"),
    ]),
]

BOZZA_PDR125 = [
    ("SG-1", "Politica, pianificazione e responsabilità", "MT CN 125_2 · MT CN 125_3 · MT CN 125_4", [
        ("Politica", "La politica per la parità di genere è approvata dalla direzione, comunicata e disponibile?"),
        ("Piano", "Il piano strategico ha obiettivi, responsabili, risorse e tempi ed è riesaminato?"),
        ("Rischi", "Rischi e opportunità per la parità di genere sono valutati e le leggi applicabili aggiornate?"),
        ("Ruoli", "Sono definiti il comitato guida e le responsabilità per la parità di genere?"),
    ]),
    ("A-1", "Cultura e strategia", "MT CN 125_11 · MT CN 125_12", [
        ("Cultura", "Formazione e comunicazione su parità e inclusione sono pianificate e registrate, con linguaggio inclusivo?"),
        ("Stakeholder", "Il rapporto con gli stakeholder sui temi di parità è gestito e documentato?"),
    ]),
    ("A-2", "Governance", "MT CN 125_4 · MT CN 125_10", [
        ("Governance", "La parità è presidiata negli organi di governo, con budget dedicato e monitoraggio dei risultati?"),
    ]),
    ("A-3", "Processi HR", "MT CN 125_5 · MT CN 125_6 · MOD.202", [
        ("Selezione", "Selezione e assunzione seguono criteri neutrali rispetto al genere, con evidenze di valutazione?"),
        ("Carriera", "I percorsi di carriera e le valutazioni sono documentati e privi di discriminazioni?"),
    ]),
    ("A-4", "Opportunità di crescita e inclusione delle donne", "MT CN 125_6 · MT CN 125_11", [
        ("Crescita", "Sono monitorate la presenza femminile per ruolo e livello e l'accesso a formazione e promozioni?"),
    ]),
    ("A-5", "Equità remunerativa per genere", "MT CN 125_7", [
        ("Retribuzione", "Il divario retributivo per genere a parità di ruolo è misurato e sono pianificate azioni sugli scostamenti?"),
    ]),
    ("A-6", "Tutela della genitorialità e conciliazione vita-lavoro", "MT CN 125_8 · MT CN 125_9", [
        ("Genitorialità", "Sono attuate le misure di tutela della genitorialità e di rientro dopo i congedi?"),
        ("Conciliazione", "Le misure di conciliazione (orari, lavoro agile, servizi) sono disponibili e utilizzate?"),
    ]),
    ("SG-2", "Prevenzione di abusi e molestie", "MT CN 125_10", [
        ("Molestie", "Esistono canali di segnalazione riservati, gestione delle segnalazioni e formazione sulla prevenzione?"),
    ]),
    ("SG-3", "Indicatori e monitoraggio", "MT CN 125_13 · riesame della direzione", [
        ("KPI", "I KPI delle sei aree sono calcolati con metodo documentato e il punteggio è confrontato con la soglia della prassi?"),
        ("Riesame", "I risultati sono riesaminati dalla direzione con azioni di miglioramento?"),
    ]),
]

BOZZE = {
    ChecklistModello.CODICE_ISO45001: BOZZA_ISO45001,
    ChecklistModello.CODICE_PDR125: BOZZA_PDR125,
}


def modello_attivo(codice: str) -> ChecklistModello | None:
    return ChecklistModello.objects.filter(codice=codice, attivo=True).order_by("-revisione").first()


def modelli_per_audit(audit) -> list[ChecklistModello]:
    return [m for flag, codice in ChecklistModello.CODICE_PER_NORMA.items()
            if getattr(audit, flag, False) and (m := modello_attivo(codice))]


def usato(modello: ChecklistModello) -> bool:
    return (AuditEsito.objects.filter(domanda__sezione__modello=modello).exists()
            or AuditSezioneCar.objects.filter(sezione__modello=modello).exists())


def modificabile(modello: ChecklistModello) -> bool:
    return not modello.attivo and not usato(modello)


def _verifica_modificabile(modello: ChecklistModello) -> None:
    modello = ChecklistModello.objects.get(pk=modello.pk)  # stato dal DB, non dall'istanza in memoria
    if modello.attivo:
        raise ChecklistNonModificabile("La revisione è attiva: apri una nuova revisione per modificarla.")
    if usato(modello):
        raise ChecklistNonModificabile("La revisione è già stata usata in un audit: apri una nuova revisione.")


@transaction.atomic
def proponi_bozza(codice: str, *, utente) -> ChecklistModello:
    """Bozza di base Rev.0, inattiva. Solo se per la norma non esiste ancora nessuna revisione."""
    if codice not in BOZZE:
        raise ChecklistNonModificabile("Per questa norma la checklist si importa dal modulo aziendale.")
    if ChecklistModello.objects.filter(codice=codice).exists():
        raise ChecklistNonModificabile("Esiste già una checklist per questa norma: apri una nuova revisione.")
    info = NORME[codice]
    modello = ChecklistModello.objects.create(
        codice=codice, norma=info["norma"], revisione=0, titolo=info["titolo"], attivo=False,
        origine="Bozza di base proposta dal portale: da verificare", preparato_da=utente,
        motivo="Prima emissione",
    )
    for ordine_sezione, (codice_sez, titolo, criteri, domande) in enumerate(BOZZE[codice], start=1):
        sezione = ChecklistSezione.objects.create(
            modello=modello, codice=codice_sez, titolo=titolo, criteri=criteri, ordine=ordine_sezione * 10,
        )
        for ordine, (punti, testo) in enumerate(domande, start=1):
            ChecklistDomanda.objects.create(sezione=sezione, punti=punti, testo=testo, ordine=ordine * 10)
    return modello


@transaction.atomic
def nuova_revisione(modello: ChecklistModello, *, utente, motivo: str) -> ChecklistModello:
    """Copia la revisione indicata in una nuova revisione inattiva (numero = massimo + 1)."""
    if not (motivo or "").strip():
        raise ChecklistNonModificabile("Indica il motivo della nuova revisione.")
    numero = (ChecklistModello.objects.filter(codice=modello.codice).aggregate(n=Max("revisione"))["n"] or 0) + 1
    nuova = ChecklistModello.objects.create(
        codice=modello.codice, norma=modello.norma, revisione=numero, titolo=modello.titolo, attivo=False,
        origine=f"Copia della Rev.{modello.revisione}"[:255], preparato_da=utente, motivo=motivo.strip()[:255],
    )
    for sezione in modello.sezioni.prefetch_related("domande"):
        copia = ChecklistSezione.objects.create(
            modello=nuova, codice=sezione.codice, titolo=sezione.titolo, criteri=sezione.criteri, ordine=sezione.ordine,
        )
        for domanda in sezione.domande.all():
            ChecklistDomanda.objects.create(
                sezione=copia, punti=domanda.punti, testo=domanda.testo, ordine=domanda.ordine, attiva=domanda.attiva,
            )
    return nuova


@transaction.atomic
def attiva(modello: ChecklistModello, *, utente) -> ChecklistModello:
    modello = ChecklistModello.objects.select_for_update().get(pk=modello.pk)
    if not ChecklistDomanda.objects.filter(sezione__modello=modello, attiva=True).exists():
        raise ChecklistNonModificabile("La checklist non ha domande attive.")
    ChecklistModello.objects.filter(codice=modello.codice, attivo=True).exclude(pk=modello.pk).update(attivo=False)
    modello.attivo = True
    modello.attivato_da = utente
    modello.attivato_il = timezone.now()
    modello.save(update_fields=["attivo", "attivato_da", "attivato_il"])
    return modello


@transaction.atomic
def disattiva(modello: ChecklistModello) -> ChecklistModello:
    modello.attivo = False
    modello.save(update_fields=["attivo"])
    return modello


def salva_sezione(sezione: ChecklistSezione) -> ChecklistSezione:
    _verifica_modificabile(sezione.modello)
    sezione.full_clean()
    sezione.save()
    return sezione


def salva_domanda(domanda: ChecklistDomanda) -> ChecklistDomanda:
    _verifica_modificabile(domanda.sezione.modello)
    domanda.full_clean()
    domanda.save()
    return domanda


def rimuovi_domanda(domanda: ChecklistDomanda) -> None:
    _verifica_modificabile(domanda.sezione.modello)
    domanda.delete()


def rimuovi_sezione(sezione: ChecklistSezione) -> None:
    _verifica_modificabile(sezione.modello)
    sezione.delete()
