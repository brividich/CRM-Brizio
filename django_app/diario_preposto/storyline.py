"""Storyline di una segnalazione: tutto quello che le è successo, in ordine.

Mette insieme fonti diverse senza duplicarle:
- il record (fatto segnalato, inserimento nel portale, eliminazione in corso);
- gli allegati, anche quelli rimossi (chi e quando li ha aggiunti e tolti);
- l'audit della scheda (modifiche campo per campo, eliminazioni, ripristini,
  download degli allegati);
- le mail automatiche partite per la segnalazione (registro EmailInviata).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from django.utils import timezone

from .cruscotto import GIORNI_RITARDO_REGISTRAZIONE

# Etichette (verbose_name) dei campi di eliminazione, come le scrive lo storico.
ETICHETTE_ELIMINAZIONE = {"Eliminata il", "Eliminata da", "Motivo eliminazione"}


@dataclass
class Evento:
    quando: datetime
    tipo: str            # fatto | registrata | modifica | allegato | allegato_rimosso | download | mail | eliminata | ripristinata
    titolo: str
    chi: str = ""
    stato: str = ""      # "" | avviso | critico
    righe: list = field(default_factory=list)   # [{"campo","prima","dopo"}]
    note: list = field(default_factory=list)    # testo libero


def _nome(user) -> str:
    if not user:
        return ""
    return (user.get_full_name() or user.get_username() or "").strip()


def _locale(dt):
    return timezone.localtime(dt) if dt and timezone.is_aware(dt) else dt


def costruisci_storyline(segnalazione) -> dict:
    from core.audit import storico_leggibile, storico_oggetto

    eventi: list[Evento] = []

    if segnalazione.data_segnalazione:
        eventi.append(Evento(segnalazione.data_segnalazione, "fatto", "Fatto segnalato",
                             chi=segnalazione.chi_segnala or segnalazione.preposto))

    ritardo_giorni = None
    if segnalazione.created_at:
        registrata = Evento(segnalazione.created_at, "registrata",
                            f"Registrata nel diario come {segnalazione.codice_identificativo or '-'}",
                            chi=_nome(segnalazione.creato_da) or segnalazione.chi_segnala)
        if segnalazione.data_segnalazione:
            ritardo_giorni = (_locale(segnalazione.created_at).date()
                              - _locale(segnalazione.data_segnalazione).date()).days
            if ritardo_giorni > GIORNI_RITARDO_REGISTRAZIONE:
                registrata.stato = "avviso"
                registrata.note.append(f"Inserita {ritardo_giorni} giorni dopo il fatto.")
        eventi.append(registrata)

    allegati = list(segnalazione.allegati.select_related("caricato_da", "rimosso_da").order_by("uploaded_at", "id"))
    for a in allegati:
        ev = Evento(a.uploaded_at, "allegato", f"Allegato aggiunto: {a.nome_file}", chi=_nome(a.caricato_da))
        if a.sha256:
            ev.note.append(f"Impronta SHA-256 {a.sha256[:16]}…")
        eventi.append(ev)
        if a.rimosso_il:
            eventi.append(Evento(a.rimosso_il, "allegato_rimosso", f"Allegato rimosso: {a.nome_file}",
                                 chi=_nome(a.rimosso_da), stato="avviso",
                                 note=["Il file resta archiviato sul server."]))

    n_modifiche = 0
    for voce in storico_leggibile(storico_oggetto(segnalazione, limit=300)):
        dettaglio = voce.dettaglio if isinstance(voce.dettaglio, dict) else {}
        if voce.azione == "auto_update":
            righe_elim = [r for r in voce.righe if r["campo"] in ETICHETTE_ELIMINAZIONE]
            righe_altre = [r for r in voce.righe if r["campo"] not in ETICHETTE_ELIMINAZIONE]
            if righe_elim:
                eliminata = any(r["campo"] == "Eliminata il" and r["dopo"] != "—" for r in righe_elim)
                motivo = next((r["dopo"] for r in righe_elim if r["campo"] == "Motivo eliminazione"), "")
                eventi.append(Evento(voce.created_at, "eliminata" if eliminata else "ripristinata",
                                     "Eliminata dal registro" if eliminata else "Ripristinata nel registro",
                                     chi=voce.utente_display, stato="critico" if eliminata else "",
                                     note=[f"Motivo: {motivo}"] if eliminata and motivo and motivo != "—" else []))
            if righe_altre:
                n_modifiche += 1
                eventi.append(Evento(voce.created_at, "modifica",
                                     "Modificata: " + ", ".join(r["campo"].lower() for r in righe_altre),
                                     chi=voce.utente_display, righe=righe_altre))
        elif voce.azione == "download_allegato" and dettaglio.get("esito") == "success":
            eventi.append(Evento(voce.created_at, "download",
                                 f"Allegato scaricato: {dettaglio.get('filename') or '-'}", chi=voce.utente_display))
        elif voce.azione == "download_allegato" and dettaglio.get("esito") == "integrita_ko":
            eventi.append(Evento(voce.created_at, "download", "Download bloccato: file diverso da quello caricato",
                                 chi=voce.utente_display, stato="critico"))

    mail_ok = mail_ko = 0
    try:
        from automazioni.models import EmailInviata

        for m in EmailInviata.objects.filter(sorgente="diario_preposto", record_id=str(segnalazione.pk)).order_by("inviata_il"):
            destinatari = ", ".join(x.strip() for x in (m.destinatari or "").replace(";", ",").split(",") if x.strip())
            if m.esito == EmailInviata.ESITO_ERRORE:
                mail_ko += 1
                eventi.append(Evento(m.inviata_il, "mail", f"Notifica NON partita: {m.oggetto or '-'}",
                                     stato="critico", note=[f"A: {destinatari}" if destinatari else "", m.errore[:200]]))
            else:
                mail_ok += 1
                eventi.append(Evento(m.inviata_il, "mail", f"Notifica inviata: {m.oggetto or '-'}",
                                     note=[f"A: {destinatari}"] if destinatari else []))
    except Exception:
        pass

    for ev in eventi:
        ev.note = [n for n in ev.note if n]
    eventi.sort(key=lambda e: (e.quando, 0 if e.tipo == "fatto" else 1))

    oggi = timezone.localdate()
    giorni_aperta = (oggi - _locale(segnalazione.data_segnalazione).date()).days if segnalazione.data_segnalazione else None
    ultima = max((e for e in eventi if e.tipo != "fatto"), key=lambda e: e.quando, default=None)
    allegati_attivi = [a for a in allegati if not a.rimosso_il]
    return {
        "eventi": eventi,
        "riepilogo": {
            "giorni_dal_fatto": giorni_aperta,
            "ritardo_giorni": ritardo_giorni,
            "ritardo_avviso": ritardo_giorni is not None and ritardo_giorni > GIORNI_RITARDO_REGISTRAZIONE,
            "allegati": len(allegati_attivi),
            "allegati_rimossi": len(allegati) - len(allegati_attivi),
            "allegati_senza_impronta": sum(1 for a in allegati_attivi if not a.sha256),
            "modifiche": n_modifiche,
            "mail_ok": mail_ok,
            "mail_ko": mail_ko,
            "ultima_attivita": ultima.quando if ultima else None,
            "ultima_attivita_chi": ultima.chi if ultima else "",
        },
    }
