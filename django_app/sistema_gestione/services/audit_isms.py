"""Audit ISMS (MT CN 276): rapporto MOD.168 con requisiti ISO/IEC 27001 e 93 controlli ISO/IEC 27002.

I livelli di applicazione partono da quelli della SoA approvata in vigore (scala 0-4 del MOD.165,
4 = pienamente applicato): l'auditor li conferma o li corregge motivando. NC e AP diventano voci
del Registro OFI MOD.174; i COM restano commenti nel rapporto. Dopo la chiusura i livelli emersi
possono aprire una nuova revisione della SoA in bozza, da proporre e approvare con il flusso SoA.
"""
from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import (
    RILIEVO_ISMS_AP,
    RILIEVO_ISMS_COM,
    RILIEVO_ISMS_NC,
    Audit,
    AuditIsms,
    AuditIsmsControllo,
    AuditIsmsRequisito,
    ControlloIso27002,
    SoaRevisione,
)

# Righe della tabella «ISO 27001:2022 - Evidenze e rilievi» del MOD.168 Rev.2.
REQUISITI_MOD168 = [
    ("4.3", "Campo d'applicazione del SGSI"),
    ("5.2", "Politica per la sicurezza delle informazioni"),
    ("6.1.2", "Processo di valutazione del rischio"),
    ("6.1.3 d)", "Dichiarazione di Applicabilità"),
    ("6.1.3 / 8.2 / 8.3", "Processo di trattamento del rischio; risultati della valutazione e del trattamento del rischio"),
    ("6.2", "Obiettivi per la sicurezza delle informazioni"),
    ("7.2", "Competenza"),
    ("7.5", "Informazioni documentate di origine esterna"),
    ("8.1", "Pianificazione e controlli operativi"),
    ("9.1", "Risultati dei monitoraggi e misurazioni"),
    ("9.2", "Audit interno"),
    ("9.3", "Riesame di direzione"),
    ("10.1", "Non conformità ed azioni correttive"),
    ("Obblighi", "Obblighi di conformità rilevanti / requisiti cogenti rilevanti in merito a processi / prodotti / servizi"),
    ("Controlli", "Famiglie di controlli applicati ISO/IEC 27002:2022"),
]

RILIEVI_REGISTRO = {RILIEVO_ISMS_NC, RILIEVO_ISMS_AP}


def soa_in_vigore() -> SoaRevisione | None:
    from .soa import revisione_in_vigore

    return revisione_in_vigore()


@transaction.atomic
def assicura_isms(audit: Audit) -> AuditIsms | None:
    """Crea (una volta) dati MOD.171/168, righe requisiti e i 93 controlli; non sovrascrive nulla."""
    if not audit.is_isms:
        return None
    from .soa import assicura_catalogo

    dati, creato = AuditIsms.objects.get_or_create(
        audit=audit,
        defaults={"sito_campo": audit.sede, "sito_indirizzo": audit.sede},
    )
    for ordine, (codice, titolo) in enumerate(REQUISITI_MOD168, start=1):
        AuditIsmsRequisito.objects.get_or_create(
            audit=audit, codice=codice, defaults={"titolo": titolo, "ordine": ordine * 10},
        )
    assicura_catalogo()
    soa = dati.soa_revisione or soa_in_vigore()
    if soa and not dati.soa_revisione_id:
        dati.soa_revisione = soa
        dati.save(update_fields=["soa_revisione", "updated_at"])
    livelli = dict(soa.voci.values_list("controllo_id", "livello")) if soa else {}
    presenti = set(audit.isms_controlli.values_list("controllo_id", flat=True))
    nuovi = [
        AuditIsmsControllo(
            audit=audit, controllo=controllo,
            livello_soa=livelli.get(controllo.pk), livello=livelli.get(controllo.pk),
        )
        for controllo in ControlloIso27002.objects.all() if controllo.pk not in presenti
    ]
    # Inserimenti singoli: un batch INSERT su SQL Server dentro un savepoint è fragile.
    for riga in nuovi:
        riga.save()
    return dati


def _nome_utente(user) -> str:
    return (user.get_full_name() or user.get_username()).strip() if user else ""


@transaction.atomic
def sincronizza_ofi_isms(riga):
    """NC e AP: una sola voce MOD.174 con ISO 27001 e riferimento al requisito o al controllo."""
    from gestione_specifiche.models import RegistroOFI
    from gestione_specifiche.registro_ofi import prossimo_numero, registra_evento

    modello = type(riga)
    riga = modello.objects.select_for_update().select_related("audit").get(pk=riga.pk)
    if riga.rilievo not in RILIEVI_REGISTRO or riga.ofi_id:
        return riga.ofi
    ct = ContentType.objects.get_for_model(modello)
    esistente = RegistroOFI.objects.filter(content_type=ct, object_id=riga.pk).first()
    if esistente:
        riga.ofi = esistente
        riga.save(update_fields=["ofi", "updated_at"])
        return esistente
    audit = riga.audit
    opportunita = riga.evidenze
    if riga.rilievo == RILIEVO_ISMS_NC and riga.gravita:
        opportunita = f"[{riga.get_gravita_display()}] {opportunita}"
    dati = {
        "data_apertura": audit.data_inizio,
        "tipo": RegistroOFI.TIPO_NC if riga.rilievo == RILIEVO_ISMS_NC else RegistroOFI.TIPO_OFI,
        "norma_iso27001": True,
        "norma_en9100": audit.en9100,
        "norma_iso45001": audit.iso45001,
        "norma_iso14001": audit.iso14001,
        "norma_pdr125": audit.pdr125,
        "rif_norma": riga.riferimento[:200],
        "fonte": "Audit interno ISMS",
        "priorita": RegistroOFI.PRIORITA_ALTA if riga.gravita == "MAGGIORE" else RegistroOFI.PRIORITA_MEDIA,
        "ref": audit.numero[:100],
        "processo": audit.processi[:200],
        "opportunita": opportunita,
        "modulo_origine": "sistema_gestione",
        "content_type": ct,
        "object_id": riga.pk,
    }
    processi = list(audit.processi_catalogo.values_list("pk", flat=True)[:2])
    if len(processi) == 1:
        dati["processo_sgi_id"] = processi[0]
    for tentativo in range(2):
        try:
            with transaction.atomic():
                voce = RegistroOFI.objects.create(numero=prossimo_numero(), **dati)
            break
        except IntegrityError:
            if tentativo:
                raise
    riga.ofi = voce
    riga.save(update_fields=["ofi", "updated_at"])
    registra_evento(voce, "CREATA", a=voce.get_fase_display(), nota=f"Dal rilievo dell'audit ISMS {audit.numero}")
    return voce


@transaction.atomic
def salva_riga(riga, *, utente):
    """Salva requisito o controllo; un rilievo già nel registro non cambia tipo (si prosegue nel MOD.174)."""
    precedente = type(riga).objects.filter(pk=riga.pk).values("rilievo", "ofi_id", "ofi__numero").first() if riga.pk else None
    if precedente and precedente["ofi_id"]:
        if precedente["rilievo"] != riga.rilievo:
            from django.core.exceptions import ValidationError

            raise ValidationError(
                f"Il rilievo è già nel Registro OFI n. {precedente['ofi__numero']}: prosegui lì, "
                "non si cambia il tipo dal rapporto.",
            )
        riga.ofi_id = precedente["ofi_id"]
    riga.aggiornato_da = utente
    riga.full_clean()
    riga.save()
    Audit.objects.filter(pk=riga.audit_id).update(riepilogo_generato="")
    if riga.rilievo in RILIEVI_REGISTRO:
        sincronizza_ofi_isms(riga)
    return riga


def righe_con_rilievo(audit: Audit) -> list:
    righe = list(audit.isms_requisiti.exclude(rilievo="").select_related("ofi"))
    righe += list(audit.isms_controlli.exclude(rilievo="").select_related("ofi", "controllo"))
    return righe


def contatori_isms(audit: Audit) -> dict[str, int]:
    righe = righe_con_rilievo(audit)
    controlli = list(audit.isms_controlli.values_list("livello", "livello_soa"))
    return {
        "nc": sum(r.rilievo == RILIEVO_ISMS_NC for r in righe),
        "nc_maggiori": sum(r.rilievo == RILIEVO_ISMS_NC and r.gravita == "MAGGIORE" for r in righe),
        "nc_minori": sum(r.rilievo == RILIEVO_ISMS_NC and r.gravita == "MINORE" for r in righe),
        "com": sum(r.rilievo == RILIEVO_ISMS_COM for r in righe),
        "ap": sum(r.rilievo == RILIEVO_ISMS_AP for r in righe),
        "controlli": len(controlli),
        "valutati": sum(livello is not None for livello, _soa in controlli),
        "diversi_da_soa": sum(livello is not None and soa is not None and livello != soa for livello, soa in controlli),
    }


def problemi_rapporto_isms(audit: Audit) -> list[dict]:
    """Voci mancanti del MOD.168 prima della firma, con l'ancora della pagina ISMS."""
    problemi = []

    def manca(condizione, testo, sezione):
        if condizione:
            problemi.append({"testo": testo, "sezione": sezione})

    dati = getattr(audit, "isms", None) if audit.pk else None
    if dati is None:
        return [{"testo": "Apri il rapporto ISMS (MOD.168): i dati non sono ancora stati creati.", "sezione": "isms"}]
    manca(not (dati.campo_date.strip() or dati.remoto_date.strip()),
          "MOD.168: indica le date dell'attività in campo o in remoto.", "isms-testata")
    manca(bool(dati.remoto_date.strip()) and dati.remoto_percentuale is None,
          "MOD.168: indica la percentuale di attività in remoto.", "isms-testata")
    for campo, etichetta in (("modifiche_sistema", "sistema di gestione"), ("modifiche_campo", "campo di applicazione"),
                             ("modifiche_addetti", "numero addetti")):
        valore = getattr(dati, campo)
        manca(not valore, f"MOD.168: indica se ci sono modifiche al {etichetta}.", "isms-modifiche")
        manca(valore == "SI" and not getattr(dati, campo + "_note").strip(),
              f"MOD.168: specifica le modifiche al {etichetta}.", "isms-modifiche")
    manca(not dati.efficacia_ncmi, "MOD.168: valuta le azioni sulle NC minori del precedente audit.", "isms-valutazioni")
    manca(not dati.report_precedenti, "MOD.168: valuta il trattamento dei rilievi degli ultimi due audit.", "isms-valutazioni")
    manca(not dati.commenti_precedenti, "MOD.168: indica se sono stati analizzati i commenti del precedente audit.", "isms-valutazioni")
    for req in audit.isms_requisiti.all():
        manca(not req.evidenze.strip(), f"Requisito {req.codice}: registra le evidenze.", f"isms-req-{req.pk}")
        manca(req.rilievo in RILIEVI_REGISTRO and not req.ofi_id,
              f"Requisito {req.codice}: manca il collegamento al Registro OFI.", f"isms-req-{req.pk}")
    for riga in audit.isms_controlli.select_related("controllo"):
        codice = riga.controllo.codice
        manca(riga.livello is None, f"Controllo {codice}: indica l'applicazione (0-4).", f"isms-ctrl-{riga.pk}")
        manca(riga.differisce_da_soa and not riga.evidenze.strip(),
              f"Controllo {codice}: il livello differisce dalla SoA ({riga.livello_soa}), motiva nel commento.",
              f"isms-ctrl-{riga.pk}")
        manca(riga.rilievo in RILIEVI_REGISTRO and not riga.ofi_id,
              f"Controllo {codice}: manca il collegamento al Registro OFI.", f"isms-ctrl-{riga.pk}")
    if efficacia_non_efficace(dati):
        manca(not any(r.rilievo == RILIEVO_ISMS_NC and r.gravita == "MAGGIORE" for r in righe_con_rilievo(audit)),
              "MOD.168: con azioni sulle NC minori non efficaci va rilasciata una NC maggiore.", "isms-valutazioni")
    return problemi


def efficacia_non_efficace(dati: AuditIsms) -> bool:
    return dati.efficacia_ncmi == "NON_EFFICACI"


def problemi_chiusura_isms(audit: Audit) -> list[str]:
    """Come per le NC EN 9100: ogni NC deve avere la CAR con il piano azioni approvato."""
    problemi = []
    for riga in righe_con_rilievo(audit):
        if riga.rilievo != RILIEVO_ISMS_NC:
            continue
        car = getattr(riga.ofi, "car_procedurale", None) if riga.ofi_id else None
        if not riga.ofi_id:
            problemi.append(f"{riga.riferimento}: la NC non è nel Registro OFI.")
        elif car is None:
            problemi.append(f"{riga.riferimento}: apri la CAR della NC n. {riga.ofi.numero}.")
        elif not car.approvata_il:
            problemi.append(f"{riga.riferimento}: il piano azioni della NC n. {riga.ofi.numero} non è ancora approvato.")
    return problemi


def riepilogo_isms(audit: Audit) -> str:
    c = contatori_isms(audit)
    righe = [
        f"Audit ISMS {audit.numero} del {audit.data_inizio:%d/%m/%Y} - ISO/IEC 27001, 27002:2022",
        f"Controlli valutati: {c['valutati']}/{c['controlli']}; livelli diversi dalla SoA: {c['diversi_da_soa']}.",
        f"Rilievi: NC {c['nc']} (maggiori {c['nc_maggiori']}, minori {c['nc_minori']}); COM {c['com']}; AP {c['ap']}.",
    ]
    for riga in righe_con_rilievo(audit):
        testo = f"\n{riga.riferimento} - {riga.get_rilievo_display()}"
        if riga.gravita:
            testo += f" ({riga.get_gravita_display()})"
        righe.append(f"{testo}\n{riga.evidenze}")
        if riga.ofi_id:
            righe.append(f"Registro MOD.174 n. {riga.ofi.numero}.")
    return "\n".join(righe)


def azioni_correttive(audit: Audit) -> list[dict]:
    """«Elenco azioni correttive» del MOD.168: NC con azione, responsabile e scadenza dal registro."""
    elenco = []
    for riga in righe_con_rilievo(audit):
        if riga.rilievo != RILIEVO_ISMS_NC:
            continue
        voce = riga.ofi
        car = getattr(voce, "car_procedurale", None) if voce else None
        elenco.append({
            "nc": f"{riga.riferimento}" + (f" - MOD.174 n. {voce.numero}" if voce else ""),
            "azione": (car.azione if car and car.azione else (voce.plan if voce else "")) or "",
            "responsabile": (_nome_utente(car.responsabile) if car else "") or (voce.proprietario if voce else ""),
            "scadenza": (car.scadenza_chiusura if car else None) or (voce.data_richiesta if voce else None),
        })
    return elenco


@transaction.atomic
def proponi_aggiornamento_soa(audit: Audit, *, utente) -> tuple[SoaRevisione, int]:
    """Nuova revisione SoA in bozza con i livelli emersi dall'audit chiuso. Restituisce (revisione, variazioni)."""
    from .soa import TransizioneNonAmmessa, nuova_revisione

    if not audit.is_isms or audit.stato != Audit.STATO_CHIUSO:
        raise TransizioneNonAmmessa("La proposta di aggiornamento della SoA si apre da un audit ISMS chiuso.")
    dati = AuditIsms.objects.select_for_update().get(audit=audit)
    if dati.soa_proposta_id:
        raise TransizioneNonAmmessa(f"Questo audit ha già proposto la revisione {dati.soa_proposta.numero} della SoA.")
    variazioni = {
        r.controllo_id: r for r in audit.isms_controlli.select_related("controllo")
        if r.livello is not None and r.differisce_da_soa
    }
    if not variazioni:
        raise TransizioneNonAmmessa("I livelli dell'audit coincidono con la SoA: nessuna revisione da proporre.")
    revisione = nuova_revisione(
        utente=utente, motivo=f"Esiti dell'audit ISMS {audit.numero}"[:255], origine=f"Audit {audit.numero} (MOD.168)"[:255],
    )
    for voce in revisione.voci.filter(controllo_id__in=variazioni):
        riga = variazioni[voce.controllo_id]
        voce.livello = riga.livello
        nota = f"Audit {audit.numero}: livello {riga.livello_soa} → {riga.livello}. {riga.evidenze.strip()}".strip()
        voce.giustificazione = f"{voce.giustificazione.strip()}\n{nota}".strip()
        voce.aggiornata_da = utente
        voce.save(update_fields=["livello", "giustificazione", "aggiornata_da", "updated_at"])
    dati.soa_proposta = revisione
    dati.soa_proposta_il = timezone.now()
    dati.save(update_fields=["soa_proposta", "soa_proposta_il", "updated_at"])
    return revisione, len(variazioni)
