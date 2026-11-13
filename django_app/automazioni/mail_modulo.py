"""Impostazioni mail dei moduli, modificabili anche dal flusso in Automazioni.

Ogni voce punta allo stesso dato che il modulo legge e scrive nella sua pagina
(una chiave ``SiteConfig``, un campo del modello impostazioni, un testo
personalizzabile): cambiarlo qui o nel modulo è la stessa cosa. Il pannello
«Invia un messaggio di posta» del flusso mostra i campi di ``IMPOSTAZIONI``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Campo:
    chiave: str
    etichetta: str
    leggi: Callable[[], str]
    salva: Callable[[str], str]  # ritorna il messaggio d'errore, "" se salvato
    righe: int = 1
    aiuto: str = ""


def _valida_indirizzi(valore: str) -> str:
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    from .mail_config import elenco_indirizzi

    for indirizzo in elenco_indirizzi(valore):
        try:
            validate_email(indirizzo)
        except ValidationError:
            return f"Indirizzo email non valido: «{indirizzo}»."
    return ""


def siteconfig(chiave: str, etichetta: str, *, aiuto: str = "", indirizzi: bool = True, righe: int = 2) -> Campo:
    """Elenco (o testo) su ``core.SiteConfig``: la stessa chiave che usa il modulo."""
    def leggi() -> str:
        from core.models import SiteConfig

        return SiteConfig.get(chiave, "") or ""

    def salva(valore: str) -> str:
        from core.models import SiteConfig

        from .mail_config import elenco_indirizzi

        valore = (valore or "").strip()
        if indirizzi:
            errore = _valida_indirizzi(valore)
            if errore:
                return errore
            valore = ", ".join(dict.fromkeys(elenco_indirizzi(valore)))
        SiteConfig.set(chiave, valore, f"Destinatari mail: {etichetta}")
        return ""

    return Campo(f"sc:{chiave}", etichetta, leggi, salva, righe, aiuto)


def modello(percorso: str, campo: str, etichetta: str, *, carica: str = "carica",
            aiuto: str = "", indirizzi: bool = True, righe: int = 2, separatore: str = ", ", uno_solo: bool = False) -> Campo:
    """Campo del modello impostazioni del modulo (singleton letto con ``Modello.<carica>()``)."""
    def _istanza():
        from django.apps import apps

        app_label, nome = percorso.split(".")
        return getattr(apps.get_model(app_label, nome), carica)()

    def leggi() -> str:
        return str(getattr(_istanza(), campo, "") or "")

    def salva(valore: str) -> str:
        from .mail_config import elenco_indirizzi

        valore = (valore or "").strip()
        if indirizzi:
            errore = _valida_indirizzi(valore)
            if errore:
                return errore
            elenco = list(dict.fromkeys(elenco_indirizzi(valore)))
            if uno_solo and len(elenco) > 1:
                return f"«{etichetta}»: un solo indirizzo."
            valore = separatore.join(elenco)
        obj = _istanza()
        setattr(obj, campo, valore)
        obj.save(update_fields=[campo])
        return ""

    return Campo(f"m:{percorso}.{campo}", etichetta, leggi, salva, righe, aiuto)


def testo_reception(nome: str) -> Campo:
    """Testo personalizzabile della mail (Reception → Impostazioni); vuoto = predefinito."""
    from reception import personalizza

    t = personalizza.TESTI[nome]
    aiuto = ("Segnaposti: " + ", ".join("{" + s + "}" for s in t.segnaposti)) if t.segnaposti else ""

    def salva(valore: str) -> str:
        errore = personalizza.errore(nome, valore)
        if not errore:
            personalizza.salva(nome, valore)
        return errore

    return Campo(f"rc:{nome}", t.etichetta, lambda: personalizza.leggi(nome), salva, t.righe, aiuto)


def _avviso_it_emails() -> Campo:
    def leggi() -> str:
        from anagrafica.services.avviso_it_ingresso import configurazione

        return ", ".join(configurazione()["emails"])

    def salva(valore: str) -> str:
        from anagrafica.services.avviso_it_ingresso import configurazione, salva_configurazione

        conf = configurazione()
        errori = salva_configurazione(emails_raw=valore, utenti_ids=conf["utenti_ids"], ticket=conf["ticket"])
        return " ".join(errori)

    return Campo("it:emails", "Email dell'IT", leggi, salva, 2)


def _dpi(campo: str, etichetta: str, aiuto: str = "") -> Campo:
    return modello("dpi.DPIImpostazioni", campo, etichetta, carica="get_singleton", aiuto=aiuto, separatore="\n")


def _impostazioni() -> dict[str, dict]:
    """Codice flusso → {"dove": dove si cambia nel modulo, "campi": [Campo, ...]}."""
    reception = "Reception → Configurazione → Impostazioni"
    anag_scad = "Anagrafica → Impostazioni → Scadenze e promemoria"
    dpi = "DPI → Impostazioni"
    return {
        "reception_invito": {"dove": reception, "campi": [testo_reception("invito_oggetto"), testo_reception("invito_testo")]},
        "reception_conferma_richiesta": {"dove": reception, "campi": [testo_reception("conferma_oggetto"),
                                                                      testo_reception("conferma_testo")]},
        "reception_rifiuto": {"dove": reception, "campi": [testo_reception("rifiuto_oggetto"), testo_reception("rifiuto_testo")]},
        "anagrafica_avviso_it_ingresso": {"dove": "Anagrafica → Impostazioni → Avviso IT nuovi ingressi",
                                          "campi": [_avviso_it_emails()]},
        "idoneita_gap_mansione": {"dove": anag_scad, "campi": [
            siteconfig("idoneita_reminder_emails", "Destinatari idoneità", aiuto="In più ricevono i capireparto del reparto.")]},
        "cambio_mansione_piano": {"dove": anag_scad, "campi": [siteconfig("cambio_mansione_emails", "Destinatari cambio mansione")]},
        "onboarding_dpi_rischio": {"dove": dpi, "campi": [
            _dpi("magazzino_emails", "Email Magazzino («Da distribuire»)"),
            siteconfig("dpi_amm_emails", "Amministrazione DPI («Da distribuire»)"),
            siteconfig("dpi_car_emails", "Ripiego CAR/preposto («Controllo uso»)")]},
        "dpi_richiesta_da_approvare": {"dove": dpi, "campi": [
            siteconfig("dpi_car_emails", "Ripiego se il dipendente non ha un responsabile"),
            _dpi("notifica_email_extra", "Referenti DPI in più",
                 "Ricevono ogni nuova richiesta solo con «Email ai referenti per ogni nuova richiesta» spuntata in Impostazioni DPI.")]},
        "dpi_avviso_consegna": {"dove": dpi, "campi": [_dpi("magazzino_emails", "Email Magazzino")]},
        "dpi_consegna_annullata": {"dove": dpi, "campi": [_dpi("magazzino_emails", "Email Magazzino")]},
        "dpi_consegna_contestata": {"dove": dpi, "campi": [_dpi("magazzino_emails", "Email Magazzino")]},
        "dpi_report_consegna": {"dove": dpi, "campi": [
            _dpi("amministrazione_emails", "Email Amministrazione",
                 "Solo per le categorie con «avvisa l'Amministrazione»; il responsabile del dipendente riceve comunque.")]},
        "dpi_ordine_negozio": {"dove": dpi, "campi": [
            modello("dpi.DPIImpostazioni", "negozio_email", "Mail del negozio", carica="get_singleton", righe=1),
            _dpi("negozio_operatore_emails", "Operatore incaricato (in copia)")]},
        **{codice: {"dove": "nessuna pagina del modulo: si cambia solo qui", "campi": [
            siteconfig("mpq_msm_reminder_emails", "Destinatari MOD.128 (Qualità)")]}
           for codice in ("mpq_timbri_sospesi", "mpq_macchina_da_valutare", "mpq_qualifiche_scadenze",
                          "part145_attrezzatura_stato", "part145_scadenze")},
        "assets_it_monitoring_alerts": {"dove": "nessuna pagina del modulo: si cambia solo qui", "campi": [
            siteconfig("assets_it_monitoring_emails", "Destinatari avvisi monitoraggio IT",
                       aiuto="Vuoto: i destinatari delle manutenzioni asset, poi gli amministratori.")]},
        "report_scadenze_settimanale": {"dove": "Automazioni → Impostazioni → Report scadenze", "campi": [
            siteconfig("scadenze_email_sorveglianza_sanitaria", "Sorveglianza sanitaria (visite)"),
            siteconfig("scadenze_email_hr_personale", "HR personale (contratti)"),
            siteconfig("scadenze_email_qualifiche", "Qualifiche")]},
        "pr_assignment_lifecycle": {"dove": "CN-SGI → Amministrazione → Promemoria", "campi": [
            siteconfig("pr_reminder_digest_destinatari", "Destinatari del riepilogo settimanale",
                       aiuto="I promemoria ai singoli incaricati partono comunque.")]},
        **{codice: {"dove": "Sistema di gestione → Audit → Impostazioni", "campi": [
            siteconfig("sistema_gestione.audit_email_rsgi", "Email RSGI")]}
           for codice in ("sistema_gestione_car_solleciti", "sistema_gestione_scadenze_esterni")},
        "suggestion_corner_reminders": {"dove": "Suggestion Corner → Gestione", "campi": [
            modello("suggestion_corner.SuggestionCornerConfig", "email_responsabile_escalation",
                    "Responsabile dell'escalation", carica="load", righe=1, uno_solo=True,
                    aiuto="Un solo indirizzo. I solleciti DO/CHECK vanno comunque ai responsabili della fase.")]},
        **{codice: {"dove": "KICK-OFF → Impostazioni → Configurazione", "campi": [
            modello("tasks.TaskImpostazioni", "cc_predefinite_email", "CC predefiniti (email)", carica="get_singleton",
                    separatore="\n", aiuto="Valgono quando l'incontro non ha CC suoi; i CC scelti come utenti restano nel modulo.")]}
           for codice in ("kickoff_convocazione", "kickoff_minuta", "kickoff_annullamento")},
        "dpi_promemoria_ordine_scarpe": {"dove": dpi, "campi": [
            _dpi("negozio_operatore_emails", "Operatore incaricato degli ordini", "Vuoto: i referenti DPI.")]},
    }


def campi(codice: str) -> dict | None:
    """Campi del modulo per il pannello del flusso, con il valore attuale (None se non ce ne sono)."""
    voce = _impostazioni().get(codice)
    if not voce:
        return None
    righe = []
    for c in voce["campi"]:
        try:
            valore = c.leggi()
        except Exception:
            valore = ""
        righe.append({"nome": "mod__" + c.chiave, "etichetta": c.etichetta, "valore": valore,
                      "righe": c.righe, "aiuto": c.aiuto})
    return {"dove": voce["dove"], "campi": righe}


def salva(codice: str, dati) -> list[str]:
    """Salva i campi del modulo presenti in ``dati`` (POST). Ritorna le etichette cambiate; ValueError se non validi."""
    voce = _impostazioni().get(codice)
    if not voce:
        return []
    cambiati = []
    for c in voce["campi"]:
        nome = "mod__" + c.chiave
        if nome not in dati:
            continue
        nuovo = (dati.get(nome) or "").strip()
        try:
            attuale = (c.leggi() or "").strip()
        except Exception:
            attuale = ""
        if nuovo == attuale:
            continue
        errore = c.salva(nuovo)
        if errore:
            raise ValueError(errore)
        cambiati.append(c.etichetta)
    return cambiati
