"""Sessioni formative: aprire, valutare competenza per competenza, firmare, chiudere.

Specifica della Qualità v1.0 (23/11/2026):

- la sessione la apre la Qualità o HR («gestione») su una richiesta approvata che la prevede
  (assegnazione di mansione o acquisizione di competenza); una richiesta, una sessione;
- le righe nascono dalle competenze della mansione con il loro livello minimo; quelle che la
  persona ha già a quel livello entrano «già presenti» e non vanno rivalutate. La matrice C→M della
  specifica non esiste ancora: vale il livello minimo di ogni competenza;
- valuta il responsabile della persona, oppure la Qualità o HR;
- la modalità di una riga, una volta scelta, cambia solo verso C (corso), e il cambio resta scritto;
- si chiude quando ogni riga è fatta e ci sono le due firme: chi ha il ruolo che ha approvato (RDD
  per le mansioni, MSO per le competenze; con righe in affiancamento conferma di aver visto i
  MOD.040) e la persona, nel portale oppure su carta registrata da Qualità o HR;
- alla chiusura, in una transazione: livelli delle competenze, livello della mansione (per le
  assegnazioni), richiesta evasa, registro. Chiusa negativa: serve il motivo e la skill matrix
  non cambia.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from ..models import (
    AbilitazioneMacchina,
    AbilitazioneMacchinaStorico,
    AbilitazioneMacchinaVoce,
    LivelloSkm,
    TrainingCourse,
    TrainingEnrollment,
    TrainingSession,
    ValutazioneCompetenzaStorico,
    ordinale_livello,
)
from ..models_richieste import ContatoreRichieste, RichiestaCompetenze
from ..models_sessioni import SessioneEvento, SessioneFormativa, SessionePartecipante, SessioneRiga
from . import competenze_catalogo, struttura_vista
from . import mansionario_competenze as mc
from . import richieste as rq

S, Riga, R, Part = SessioneFormativa, SessioneRiga, RichiestaCompetenze, SessionePartecipante
LIVELLI = [c for c, _ in LivelloSkm.choices]


class SessioneNonValida(ValueError):
    """Errore da mostrare a chi sta lavorando sulla sessione."""


def _evento(sessione: S, a, azione: str, *, riga=None, prima: str = "", dopo: str = "", nota: str = "") -> None:
    SessioneEvento.objects.create(sessione=sessione, riga=riga, utente=a.user, utente_nome=(a.nome or "")[:160],
                                  azione=azione, prima=(prima or "")[:160], dopo=(dopo or "")[:160], nota=nota or "")


def _nuovo_codice() -> str:
    anno = timezone.localdate().year
    ContatoreRichieste.objects.get_or_create(prefisso="SF", anno=anno)
    contatore = ContatoreRichieste.objects.select_for_update().get(prefisso="SF", anno=anno)
    contatore.ultimo += 1
    contatore.save(update_fields=["ultimo"])
    return f"SF-{anno}-{contatore.ultimo:04d}"


def _basta(livello: str, richiesto: str) -> bool:
    return bool(livello) and ordinale_livello(livello) >= ordinale_livello(richiesto)


# ═══════════════════════════════════════════════════════════════════════════
# Aprire
# ═══════════════════════════════════════════════════════════════════════════

def motivo_non_apre(a, richiesta: R) -> str:
    """Perché questo attore non può aprire la sessione; '' se può."""
    if richiesta.senza_sessione:
        return "Sospensione e rimozione non hanno sessione formativa."
    if richiesta.stato != R.STATO_APPROVATA:
        return "La sessione si apre su una richiesta approvata."
    if S.objects.filter(richiesta=richiesta).exists():
        return "La sessione di questa richiesta è già aperta."
    if not a.gestione:
        return "La sessione la aprono la Qualità o HR."
    return ""


def _righe_nuove(richiesta: R) -> list[dict]:
    persona = richiesta.legacy_anagrafica_id
    if richiesta.tipo == R.TIPO_COMPETENZA:
        # Una riga per ogni partecipante: le valutazioni restano per persona.
        c, out = richiesta.competenza, []
        for pid in richiesta.persone_ids:
            oggi = (competenze_catalogo.livelli_noti(pid).get(c.pk) or {}).get("livello", "")
            out.append({"persona": pid, "catalogo_id": c.pk, "competenza_nome": c.nome[:150],
                        "livello_richiesto": richiesta.livello, "livello_oggi": oggi, "area_id": None})
        return out
    noti = competenze_catalogo.livelli_noti(persona)
    mansione = richiesta.mansione
    ab = rq.abilitazione(mansione, persona)
    suoi = {v.voce_id: v.livello for v in ab.voci.all()} if ab is not None else {}
    out = []
    for voce in mc.competenze(mansione):
        oggi = suoi.get(voce.pk) or ""
        if not oggi and voce.catalogo_id:
            oggi = (noti.get(voce.catalogo_id) or {}).get("livello", "")
        out.append({"persona": persona, "voce": voce, "catalogo_id": voce.catalogo_id, "competenza_nome": voce.nome[:150],
                    "livello_richiesto": voce.livello_minimo, "livello_oggi": oggi or "", "area_id": mansione.area_id})
    return out


@transaction.atomic
def apri(a, richiesta: R) -> S:
    richiesta = R.objects.select_for_update().get(pk=richiesta.pk)
    motivo = motivo_non_apre(a, richiesta)
    if motivo:
        raise SessioneNonValida(motivo)
    sessione = S.objects.create(codice=_nuovo_codice(), richiesta=richiesta, aperta_da=a.user,
                                aperta_da_nome=(a.nome or "")[:160])
    for pid in richiesta.persone_ids:
        Part.objects.create(sessione=sessione, legacy_anagrafica_id=pid)
    gia = 0
    for i, dati in enumerate(_righe_nuove(richiesta)):
        presente = _basta(dati["livello_oggi"], dati["livello_richiesto"])
        gia += presente
        Riga.objects.create(
            sessione=sessione, legacy_anagrafica_id=dati["persona"], ordine=i,
            voce=dati.get("voce"), catalogo_id=dati.get("catalogo_id"),
            competenza_nome=dati["competenza_nome"], area_id=dati.get("area_id"),
            livello_richiesto=dati["livello_richiesto"], livello_oggi=dati["livello_oggi"],
            stato=Riga.STATO_GIA_PRESENTE if presente else Riga.STATO_DA_ASSEGNARE,
            livello_raggiunto=dati["livello_oggi"] if presente else "",
        )
    _evento(sessione, a, "Sessione aperta", dopo=sessione.get_stato_display(),
            nota=f"Dalla richiesta {richiesta.codice}. Competenze già presenti: {gia}.")
    rq._evento(richiesta, a, "Sessione formativa aperta", dopo=sessione.codice)
    return sessione


# ═══════════════════════════════════════════════════════════════════════════
# Valutare
# ═══════════════════════════════════════════════════════════════════════════

def motivo_non_valuta(a, riga: Riga) -> str:
    if not riga.sessione.aperta:
        return "La sessione è chiusa."
    if riga.stato == Riga.STATO_GIA_PRESENTE:
        return "La competenza è già presente: non va rivalutata."
    if riga.sessione.firma_approvatore_il:
        return "La sessione è già firmata: le righe non cambiano più."
    if a.gestione or riga.legacy_anagrafica_id in a.team:
        return ""
    return "Valuta il responsabile della persona, la Qualità o HR."


def edizioni_persona(persona_id: int) -> list[dict]:
    """Le edizioni dei corsi a cui la persona è iscritta, le più recenti prima, per la modalità «Corso»."""
    out = []
    for i in (TrainingEnrollment.objects.filter(legacy_anagrafica_id=persona_id)
              .select_related("sessione__corso").order_by("-sessione__data_inizio")[:50]):
        e = i.sessione
        esito = i.get_stato_display() + (" · idoneo" if i.idoneo else " · non idoneo" if i.idoneo is False else "")
        out.append({"id": e.pk, "testo": f"{e.corso.codice} · {e.corso.titolo} · {e.data_inizio:%d/%m/%Y} · {esito}"})
    return out


def _da_edizione(riga: Riga, edizione_id) -> None:
    """Corso, data, docente ed esito presi dall'edizione a cui la persona è iscritta."""
    edizione = TrainingSession.objects.select_related("corso").filter(pk=edizione_id).first()
    iscrizione = TrainingEnrollment.objects.filter(sessione=edizione, legacy_anagrafica_id=riga.legacy_anagrafica_id).first()         if edizione else None
    if iscrizione is None:
        raise SessioneNonValida("La persona non è iscritta a questa edizione del corso.")
    riga.edizione, riga.corso = edizione, edizione.corso
    riga.data_corso = riga.data_corso or iscrizione.data_completamento or edizione.data_fine
    if not riga.docente_ente:
        riga.docente_ente = (getattr(edizione, "erogatore_display", "") or "")[:200]
    if not riga.verifica and iscrizione.stato == "COMPLETATO" and iscrizione.idoneo is not False:
        riga.verifica = Riga.VERIFICA_ATTESTATO


def _data(valore) -> date | None:
    if isinstance(valore, date):
        return valore
    testo = (valore or "").strip()
    if not testo:
        return None
    try:
        return date.fromisoformat(testo)
    except ValueError as exc:
        raise SessioneNonValida(f"Data non valida: {testo}.") from exc


def _ore(valore) -> Decimal | None:
    testo = str(valore or "").strip().replace(",", ".")
    if not testo:
        return None
    try:
        ore = Decimal(testo)
    except InvalidOperation as exc:
        raise SessioneNonValida("Ore non valide.") from exc
    if ore <= 0:
        raise SessioneNonValida("Le ore devono essere più di zero.")
    return ore.quantize(Decimal("0.1"))


@transaction.atomic
def valuta(a, riga: Riga, *, modalita: str, livello: str = "", nota: str = "", conferma_cambio: bool = False,
           descrizione: str = "", data_verifica=None, tutor_nome: str = "", dal=None, al=None, ore=None,
           registro=None, corso_id=None, docente_ente: str = "", data_corso=None, verifica: str = "",
           edizione_id=None) -> Riga:
    """Scrive modalità ed evidenza della riga. Con un livello è una valutazione; senza, la riga resta in acquisizione."""
    riga = Riga.objects.select_for_update().select_related("sessione").get(pk=riga.pk)
    motivo = motivo_non_valuta(a, riga)
    if motivo:
        raise SessioneNonValida(motivo)
    modalita = (modalita or "").strip().upper()
    livello = (livello or "").strip().upper()
    if modalita not in dict(Riga.MODO_CHOICES):
        raise SessioneNonValida("Scegli la modalità: pregressa, affiancamento o corso.")
    if livello and livello not in LIVELLI:
        raise SessioneNonValida("Livello non valido.")
    prima_modo = riga.modalita
    if prima_modo and modalita != prima_modo:
        if modalita != Riga.MODO_CORSO:
            raise SessioneNonValida("Una volta scelta, la modalità può cambiare solo verso «Corso».")
        if not conferma_cambio:
            raise SessioneNonValida("Per passare a «Corso» conferma il cambio: resta scritto nella storia.")

    if modalita == Riga.MODO_PREGRESSA:
        riga.descrizione = (descrizione or "").strip()
        riga.data_verifica = _data(data_verifica)
        if livello and not (riga.descrizione and riga.data_verifica):
            raise SessioneNonValida("Per la pregressa servono descrizione della verifica e data.")
    elif modalita == Riga.MODO_AFFIANCAMENTO:
        riga.tutor_nome = (tutor_nome or "").strip()[:160]
        riga.dal, riga.al, riga.ore = _data(dal), _data(al), _ore(ore)
        if riga.dal and riga.al and riga.al < riga.dal:
            raise SessioneNonValida("Il periodo finisce prima di cominciare.")
        if registro:
            riga.registro_mod040 = registro
        if livello and not (riga.tutor_nome and riga.dal and riga.ore and riga.registro_mod040):
            raise SessioneNonValida("Per l'affiancamento servono tutor, inizio, ore e il registro MOD.040 caricato.")
    else:
        riga.corso = TrainingCourse.objects.filter(pk=corso_id).first() if corso_id else None
        riga.docente_ente = (docente_ente or "").strip()[:200]
        riga.data_corso = _data(data_corso)
        riga.verifica = verifica if verifica in dict(Riga.VERIFICA_CHOICES) else ""
        riga.edizione = None
        if edizione_id:
            _da_edizione(riga, edizione_id)
        if livello and not ((riga.corso or riga.docente_ente) and riga.verifica):
            raise SessioneNonValida("Per il corso servono corso o docente/ente e una verifica: attestato, test o conferma.")

    stato_prima = riga.get_stato_display()
    riga.modalita = modalita
    riga.nota = (nota or "").strip()
    if livello:
        riga.livello_raggiunto = livello
        riga.valutato_da, riga.valutato_da_nome, riga.valutato_il = a.user, (a.nome or "")[:160], timezone.now()
        riga.stato = Riga.STATO_POSITIVA if _basta(livello, riga.livello_richiesto) else Riga.STATO_IN_ACQUISIZIONE
    else:
        riga.stato = Riga.STATO_IN_ACQUISIZIONE
    riga.save()

    s = riga.sessione
    if s.stato == S.STATO_APERTA:
        s.stato = S.STATO_IN_CORSO
        s.save(update_fields=["stato"])
    if prima_modo and modalita != prima_modo:
        _evento(s, a, "Modalità cambiata", riga=riga, prima=prima_modo, dopo=modalita, nota=riga.nota)
    _evento(s, a, "Competenza valutata" if livello else "Modalità scelta", riga=riga, prima=stato_prima,
            dopo=f"{riga.get_stato_display()}{f' · livello {livello}' if livello else ''}",
            nota=f"{riga.competenza_nome} · {riga.get_modalita_display()}")
    return riga


# ═══════════════════════════════════════════════════════════════════════════
# Firmare e chiudere
# ═══════════════════════════════════════════════════════════════════════════

def sigla_firma(sessione: S) -> str:
    return rq.sigla_approva(sessione.richiesta)


def righe_mancanti(sessione: S) -> list[Riga]:
    return [r for r in sessione.righe.all() if not r.fatta]


def ha_affiancamento(sessione: S) -> bool:
    return any(r.modalita == Riga.MODO_AFFIANCAMENTO and r.stato == Riga.STATO_POSITIVA for r in sessione.righe.all())


def motivo_non_firma_approvatore(a, sessione: S) -> str:
    if not sessione.aperta:
        return "La sessione è chiusa."
    if sessione.firma_approvatore_il:
        return "Già firmata."
    sigla = sigla_firma(sessione)
    if not a.ha(sigla):
        return f"Firma chi ha il ruolo {sigla}."
    mancanti = righe_mancanti(sessione)
    if mancanti:
        return f"Mancano {len(mancanti)} competenz{'a' if len(mancanti) == 1 else 'e'} da valutare."
    return ""


@transaction.atomic
def firma_approvatore(a, sessione: S, *, visto_mod040: bool = False) -> S:
    sessione = S.objects.select_for_update().get(pk=sessione.pk)
    motivo = motivo_non_firma_approvatore(a, sessione)
    if motivo:
        raise SessioneNonValida(motivo)
    if ha_affiancamento(sessione) and not visto_mod040:
        raise SessioneNonValida("Ci sono righe in affiancamento: conferma di aver visto i registri MOD.040.")
    sessione.firma_approvatore_da, sessione.firma_approvatore_nome = a.user, (a.nome or "")[:160]
    sessione.firma_approvatore_il, sessione.benestare_mod040 = timezone.now(), bool(visto_mod040)
    sessione.save(update_fields=["firma_approvatore_da", "firma_approvatore_nome", "firma_approvatore_il",
                                 "benestare_mod040"])
    _evento(sessione, a, f"Firma {sigla_firma(sessione)}", dopo="Firmata",
            nota="Visti i registri MOD.040." if visto_mod040 else "")
    return sessione


def da_firmare(sessione: S) -> list:
    return [p for p in sessione.partecipanti.all() if not p.firmato]


def motivo_non_firma_persona(a, sessione: S, *, su_carta: bool, persona_id: int | None = None) -> str:
    """Perché questo attore non può firmare (o registrare la firma su carta) per la persona; '' se può."""
    if not sessione.aperta:
        return "La sessione è chiusa."
    if not sessione.firma_approvatore_il:
        return f"Prima firma {sigla_firma(sessione)}."
    mancano = {p.legacy_anagrafica_id for p in da_firmare(sessione)}
    if not mancano:
        return "Le persone hanno già firmato."
    if su_carta:
        if not a.gestione:
            return "La firma su carta la registrano la Qualità o HR."
        return "" if persona_id is None or persona_id in mancano else "Questa persona ha già firmato o non è nella sessione."
    if a.legacy_id and a.legacy_id in mancano:
        return ""
    return "Nel portale firma solo la persona della sessione."


@transaction.atomic
def firma_persona(a, sessione: S, *, su_carta: bool = False, data_firma=None, file=None, persona_id=None) -> S:
    sessione = S.objects.select_for_update().get(pk=sessione.pk)
    chi = persona_id if su_carta else a.legacy_id
    if su_carta and not chi:
        mancano = da_firmare(sessione)
        chi = mancano[0].legacy_anagrafica_id if len(mancano) == 1 else None
    motivo = motivo_non_firma_persona(a, sessione, su_carta=su_carta, persona_id=chi)
    if motivo:
        raise SessioneNonValida(motivo)
    if su_carta and not chi:
        raise SessioneNonValida("Scegli la persona che ha firmato su carta.")
    oggi = timezone.localdate()
    quando = _data(data_firma) if su_carta else oggi
    if quando is None:
        raise SessioneNonValida("Scrivi la data della firma su carta.")
    if quando > oggi:
        raise SessioneNonValida("La data della firma non può essere nel futuro.")
    p = Part.objects.select_for_update().get(sessione=sessione, legacy_anagrafica_id=chi)
    p.firma_modo = Part.FIRMA_CARTA if su_carta else Part.FIRMA_PORTALE
    p.firma_il, p.firma_registrata_il, p.firma_registrata_da = quando, timezone.now(), (a.nome or "")[:160]
    if file:
        p.firma_file = file
    p.save()
    nome = struttura_vista._nomi([chi]).get(chi) or f"#{chi}"
    _evento(sessione, a, "Firma della persona", dopo=p.get_firma_modo_display(),
            nota=f"{nome}: firmata il {quando:%d/%m/%Y}" + (" · foglio caricato" if file else ""))
    return sessione


def motivo_non_chiude(a, sessione: S) -> str:
    if not sessione.aperta:
        return "La sessione è già chiusa."
    if not a.gestione:
        return "La sessione la chiudono la Qualità o HR."
    mancanti = righe_mancanti(sessione)
    if mancanti:
        return f"Mancano {len(mancanti)} competenz{'a' if len(mancanti) == 1 else 'e'} da valutare."
    if not sessione.firma_approvatore_il:
        return f"Manca la firma di {sigla_firma(sessione)}."
    mancano = da_firmare(sessione)
    if mancano:
        return "Manca la firma della persona." if len(mancano) == 1 else f"Mancano le firme di {len(mancano)} persone."
    return ""


def _applica_competenza(a, riga: Riga, abilitazioni) -> list[str]:
    """Scrive il livello raggiunto sulle competenze della persona; restituisce le righe di storia."""
    note = []
    if riga.stato != Riga.STATO_POSITIVA or not riga.livello_raggiunto:
        return note
    for ab in abilitazioni:
        voci = [v for v in ab.competenza.competenze.all()
                if (riga.voce_id and v.pk == riga.voce_id) or (riga.catalogo_id and v.catalogo_id == riga.catalogo_id)] \
            if ab.competenza_id else []
        for voce in voci:
            esistente = AbilitazioneMacchinaVoce.objects.filter(abilitazione=ab, voce=voce).first()
            prima = esistente.livello if esistente else ""
            if _basta(prima, riga.livello_raggiunto):
                continue
            AbilitazioneMacchinaVoce.objects.update_or_create(abilitazione=ab, voce=voce,
                                                              defaults={"livello": riga.livello_raggiunto})
            competenze_catalogo.registra_storico(ab, voce, prima, riga.livello_raggiunto, user=a.user)
            note.append(f"{voce.nome}: {prima or '—'} → {riga.livello_raggiunto}")
    if not note and riga.catalogo_id:
        # La competenza non è ancora richiesta da nessuna mansione della persona: resta nello storico.
        ValutazioneCompetenzaStorico.objects.create(
            legacy_anagrafica_id=riga.legacy_anagrafica_id, catalogo_id=riga.catalogo_id,
            competenza_nome=riga.competenza_nome, livello_prima=riga.livello_oggi, livello=riga.livello_raggiunto,
            valutato_da=(a.nome or "")[:200])
        note.append(f"{riga.competenza_nome}: {riga.livello_oggi or '—'} → {riga.livello_raggiunto} (solo storico)")
    return note


@transaction.atomic
def chiudi(a, sessione: S) -> S:
    sessione = S.objects.select_for_update().select_related("richiesta__mansione").get(pk=sessione.pk)
    motivo = motivo_non_chiude(a, sessione)
    if motivo:
        raise SessioneNonValida(motivo)
    richiesta = sessione.richiesta
    persona = richiesta.legacy_anagrafica_id
    per_persona: dict[int, list] = {}
    for ab in (AbilitazioneMacchina.objects.filter(legacy_anagrafica_id__in=richiesta.persone_ids, in_lista=True)
               .select_related("competenza").prefetch_related("competenza__competenze")):
        per_persona.setdefault(ab.legacy_anagrafica_id, []).append(ab)
    storia = []
    for riga in sessione.righe.all():
        storia += _applica_competenza(a, riga, per_persona.get(riga.legacy_anagrafica_id, []))
    if richiesta.tipo == R.TIPO_AGGIUNTA:
        ab = rq.abilitazione(richiesta.mansione, persona)
        if ab is None:
            raise SessioneNonValida("La persona non ha più la mansione in skill matrix: apri una nuova richiesta.")
        prima = ab.livello
        if not _basta(prima, richiesta.livello) or ab.stato != AbilitazioneMacchina.STATO_ATTIVA:
            ab.livello, ab.stato = richiesta.livello, AbilitazioneMacchina.STATO_ATTIVA
            ab.save(update_fields=["livello", "stato", "updated_at"])
            AbilitazioneMacchinaStorico.objects.create(
                legacy_anagrafica_id=persona, asset_id=ab.asset_id, competenza_id=ab.competenza_id,
                livello=ab.livello, data_rilevazione=timezone.localdate(),
                fonte=AbilitazioneMacchinaStorico.FONTE_MANUALE,
                note=f"Sessione {sessione.codice} chiusa (richiesta {richiesta.codice})"[:255])
            storia.append(f"Mansione {richiesta.mansione.nome}: {prima or '—'} → {ab.livello}")
            rq._evento(richiesta, a, "Skill matrix: livello della mansione", prima=prima or "—", dopo=ab.livello)
    adesso = timezone.now()
    sessione.stato, sessione.chiusa_il, sessione.chiusa_da_nome = S.STATO_POSITIVA, adesso, (a.nome or "")[:160]
    sessione.save(update_fields=["stato", "chiusa_il", "chiusa_da_nome"])
    richiesta.stato, richiesta.evasa_il = R.STATO_EVASA, adesso
    richiesta.save(update_fields=["stato", "evasa_il"])
    _evento(sessione, a, "Sessione chiusa positiva", dopo="Chiusa positiva", nota="\n".join(storia))
    rq._evento(richiesta, a, "Richiesta evasa", prima="Approvata", dopo="Evasa", nota=f"Sessione {sessione.codice}")
    return sessione


@transaction.atomic
def chiudi_negativa(a, sessione: S, *, motivo: str) -> S:
    sessione = S.objects.select_for_update().get(pk=sessione.pk)
    if not sessione.aperta:
        raise SessioneNonValida("La sessione è già chiusa.")
    if not a.gestione:
        raise SessioneNonValida("La sessione la chiudono la Qualità o HR.")
    motivo = (motivo or "").strip()
    if not motivo:
        raise SessioneNonValida("Per chiudere come negativa scrivi il motivo.")
    adesso = timezone.now()
    sessione.stato, sessione.chiusa_il = S.STATO_NEGATIVA, adesso
    sessione.chiusa_da_nome, sessione.motivo_negativo = (a.nome or "")[:160], motivo
    sessione.save(update_fields=["stato", "chiusa_il", "chiusa_da_nome", "motivo_negativo"])
    richiesta = sessione.richiesta
    richiesta.stato, richiesta.evasa_il = R.STATO_EVASA, adesso
    richiesta.save(update_fields=["stato", "evasa_il"])
    _evento(sessione, a, "Sessione chiusa negativa", dopo="Chiusa negativa", nota=motivo)
    rq._evento(richiesta, a, "Richiesta evasa con esito negativo", prima="Approvata", dopo="Evasa", nota=motivo)
    return sessione


# ═══════════════════════════════════════════════════════════════════════════
# Vedere
# ═══════════════════════════════════════════════════════════════════════════

def puo_vedere(a, sessione: S) -> bool:
    return rq.puo_vedere(a, sessione.richiesta)


def visibili(a):
    richieste = rq.visibili(a)
    return (S.objects.select_related("richiesta__mansione", "richiesta__competenza").prefetch_related("partecipanti")
            .filter(richiesta__in=richieste.values("pk")))


def tocca_a(sessione: S) -> str:
    if not sessione.aperta:
        return ""
    mancanti = [r for r in sessione.righe.all() if not r.fatta]
    if mancanti:
        return f"Responsabile: valutare {len(mancanti)} competenz{'a' if len(mancanti) == 1 else 'e'}"
    if not sessione.firma_approvatore_il:
        return f"{sigla_firma(sessione)}: firmare"
    mancano = da_firmare(sessione)
    if mancano:
        tutti = len(sessione.partecipanti.all())
        return "La persona: firmare" if tutti == 1 else f"Le persone: firmare ({tutti - len(mancano)} di {tutti})"
    return "Qualità o HR: chiudere"


def righe(sessioni) -> list[dict]:
    sessioni = list(sessioni)
    nomi = struttura_vista._nomi(sorted({p.legacy_anagrafica_id for s in sessioni for p in s.partecipanti.all()}
                                        | {s.richiesta.legacy_anagrafica_id for s in sessioni}))
    out = []
    for s in sessioni:
        tutte = list(s.righe.all())
        pid = s.richiesta.legacy_anagrafica_id
        persona = nomi.get(pid) or f"#{pid}"
        altri = len(s.partecipanti.all()) - 1
        if altri > 0:
            persona += f" e altre {altri}" if altri > 1 else " e un'altra persona"
        out.append({"sessione": s, "persona": persona, "nomi": nomi,
                    "fatte": sum(1 for r in tutte if r.fatta), "totale": len(tutte), "tocca_a": tocca_a(s)})
    return out


def _passo_firme_persone(sessione: S) -> tuple:
    tutti = list(sessione.partecipanti.all())
    firmati = sum(1 for p in tutti if p.firmato)
    if len(tutti) <= 1:
        sotto = tutti[0].get_firma_modo_display() if tutti and tutti[0].firmato else "Da firmare"
        return ("Firma della persona", sotto, firmati == len(tutti) and bool(tutti))
    return ("Firme delle persone", f"{firmati} di {len(tutti)}", firmati == len(tutti))


def passi(sessione: S) -> list[dict]:
    """Aperta → competenze valutate → firme → chiusa, con il passo corrente."""
    tutte = list(sessione.righe.all())
    fatte = sum(1 for r in tutte if r.fatta)
    sigla = sigla_firma(sessione)
    voci = [
        ("Aperta", f"{sessione.aperta_da_nome}, {timezone.localtime(sessione.aperta_il):%d/%m/%Y}", True),
        ("Competenze", f"{fatte} di {len(tutte)} valutate", fatte == len(tutte)),
        (f"Firma {sigla}", sessione.firma_approvatore_nome or "Da firmare", bool(sessione.firma_approvatore_il)),
        _passo_firme_persone(sessione),
        ("Chiusa", sessione.get_stato_display() if not sessione.aperta else "Livelli nella skill matrix", not sessione.aperta),
    ]
    out, corrente = [], None
    for nome, sotto, fatto in voci:
        stato = "fatto" if fatto else ""
        if not fatto and corrente is None:
            corrente, stato = nome, "ora"
        out.append({"nome": nome, "sotto": sotto, "stato": stato})
    if sessione.stato == S.STATO_NEGATIVA:
        out[-1]["stato"] = "respinta"
    return out


def da_fare(a) -> dict:
    """Che cosa delle sessioni aspetta questo attore."""
    out = {"da_aprire": [], "da_valutare": [], "da_firmare": [], "da_firmare_io": [], "da_chiudere": []}
    if a.gestione:
        out["da_aprire"] = rq.righe(R.objects.select_related("mansione", "competenza")
                                    .filter(stato=R.STATO_APPROVATA, tipo__in=(R.TIPO_AGGIUNTA, R.TIPO_COMPETENZA),
                                            sessione__isnull=True).order_by("decisa_il"))
    aperte = list(S.objects.select_related("richiesta__mansione", "richiesta__competenza")
                  .prefetch_related("righe", "partecipanti").filter(stato__in=S.STATI_APERTI).order_by("aperta_il"))
    for s in aperte:
        mancanti = [r for r in s.righe.all() if not r.fatta]
        senza_firma = {p.legacy_anagrafica_id for p in s.partecipanti.all() if not p.firmato}
        if mancanti and (a.gestione or any(r.legacy_anagrafica_id in a.team for r in mancanti)):
            out["da_valutare"].append(s)
        elif not mancanti and not s.firma_approvatore_il and a.ha(sigla_firma(s)):
            out["da_firmare"].append(s)
        elif s.firma_approvatore_il and a.legacy_id and a.legacy_id in senza_firma:
            out["da_firmare_io"].append(s)
        elif s.firma_approvatore_il and not senza_firma and a.gestione:
            out["da_chiudere"].append(s)
    for chiave in ("da_valutare", "da_firmare", "da_firmare_io", "da_chiudere"):
        out[chiave] = righe(out[chiave])
    return out
