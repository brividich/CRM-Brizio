"""Richieste su mansioni e competenze: chi può chiedere, chi approva, che cosa cambia.

Specifica della Qualità v1.0 (23/11/2026), tabella «Chi può creare cosa»:

- assegnazione di mansione: il responsabile della persona, HR o Direzione; approva RDD;
- sospensione e rimozione: il responsabile o MSO; approva RDD; motivazione obbligatoria;
- acquisizione di competenza: il responsabile, HR o MSO; approva MSO.

Nessuno approva la propria richiesta. Chi ha un ruolo si riconosce dalla sigla del ruolo
nel catalogo (``SIGLA_APPROVA``): gli utenti di ogni passo sono un punto aperto della
specifica, qui stanno in un posto solo.

All'approvazione:

- assegnazione: se la persona non ha ancora la mansione entra in skill matrix a livello I
  (in formazione); il livello chiesto arriva solo con la sessione formativa chiusa;
- sospensione e rimozione: la skill matrix si aggiorna subito e la richiesta è evasa;
- competenza: resta approvata in attesa della sessione formativa.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..models import (
    AbilitazioneMacchina,
    AbilitazioneMacchinaStorico,
    CompetenzaCatalogo,
    CompetenzaSkm,
    DipendenteRuoloOperativo,
    LivelloSkm,
    ordinale_livello,
)
from ..models_richieste import ContatoreRichieste, RichiestaCompetenze, RichiestaEvento
from . import competenze_catalogo, struttura_vista
from . import mansionario_competenze as mc
from . import mansionario_struttura as mstr

R = RichiestaCompetenze
SIGLA_MANSIONI, SIGLA_COMPETENZE = "RDD", "MSO"
SIGLA_APPROVA = {R.TIPO_AGGIUNTA: SIGLA_MANSIONI, R.TIPO_SOSPENSIONE: SIGLA_MANSIONI, R.TIPO_RIMOZIONE: SIGLA_MANSIONI,
                 R.TIPO_COMPETENZA: SIGLA_COMPETENZE}
PREFISSO = {R.TIPO_AGGIUNTA: "RAM", R.TIPO_SOSPENSIONE: "RAM", R.TIPO_RIMOZIONE: "RAM", R.TIPO_COMPETENZA: "RAC"}
LIVELLI = [c for c, _ in LivelloSkm.choices]


class RichiestaNonValida(ValueError):
    """Errore da mostrare a chi sta compilando o decidendo la richiesta."""


# ═══════════════════════════════════════════════════════════════════════════
# Chi è chi
# ═══════════════════════════════════════════════════════════════════════════

def titolari(sigla: str) -> set[int]:
    """Persone che oggi ricoprono il ruolo con questa sigla."""
    oggi = timezone.localdate()
    return set(DipendenteRuoloOperativo.objects.filter(ruolo__sigla=sigla, ruolo__is_active=True)
               .filter(Q(data_fine__isnull=True) | Q(data_fine__gte=oggi))
               .values_list("legacy_anagrafica_id", flat=True))


@dataclass
class Attore:
    """Chi sta guardando o agendo: il suo team e i ruoli che contano per le richieste."""

    user: object
    legacy_id: int | None = None
    nome: str = ""
    team: set = field(default_factory=set)
    gestione: bool = False       # HR, Qualità, Direzione: amministrazione anagrafica o dati HR
    sigle: set = field(default_factory=set)

    def ha(self, sigla: str) -> bool:
        return sigla in self.sigle

    @property
    def responsabile(self) -> bool:
        return bool(self.team)


def attore(request) -> Attore:
    from ..views import _current_legacy_anagrafica_id
    from ..views_mansionario import _puo_vedere
    from ..views_mio_team import membri_team

    io = _current_legacy_anagrafica_id(request)
    a = Attore(user=request.user, legacy_id=io, gestione=_puo_vedere(request))
    a.nome = (request.user.get_full_name() or request.user.get_username() or "").strip()
    if io:
        a.team = set(membri_team(io))
        a.nome = struttura_vista._nomi([io]).get(io) or a.nome
        a.sigle = {s for s in (SIGLA_MANSIONI, SIGLA_COMPETENZE) if io in titolari(s)}
    return a


def in_forza() -> set[int]:
    from . import capo_team

    return set(capo_team.mappa_capi_in_cache())


# ═══════════════════════════════════════════════════════════════════════════
# Creare
# ═══════════════════════════════════════════════════════════════════════════

def tipi_ammessi(a: Attore, persona_id: int | None = None) -> list[str]:
    """I tipi di richiesta che questo attore può creare (per questa persona, se indicata)."""
    suo = persona_id is None or persona_id in a.team
    tipi = []
    if a.gestione or (a.responsabile and suo):
        tipi.append(R.TIPO_AGGIUNTA)
    if a.ha(SIGLA_COMPETENZE) or (a.responsabile and suo):
        tipi += [R.TIPO_SOSPENSIONE, R.TIPO_RIMOZIONE]
    if a.gestione or a.ha(SIGLA_COMPETENZE) or (a.responsabile and suo):
        tipi.append(R.TIPO_COMPETENZA)
    return tipi


def persone_ammesse(a: Attore) -> list[dict]:
    """Le persone per cui l'attore può aprire almeno un tipo di richiesta."""
    ids = set(in_forza()) if (a.gestione or a.ha(SIGLA_COMPETENZE)) else set(a.team)
    nomi = struttura_vista._nomi(sorted(ids))
    righe = [{"id": i, "nome": nomi.get(i) or f"#{i}"} for i in ids]
    righe.sort(key=lambda p: p["nome"].casefold())
    return righe


def abilitazione(mansione: CompetenzaSkm, legacy_id: int) -> AbilitazioneMacchina | None:
    """La riga di skill matrix della persona sulla mansione, se è in lista."""
    chiave = {"asset_id": mansione.asset_id} if mansione.asset_id else {"competenza": mansione}
    return AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=legacy_id, in_lista=True, **chiave).first()


def _nuovo_codice(tipo: str) -> str:
    anno = timezone.localdate().year
    prefisso = PREFISSO[tipo]
    ContatoreRichieste.objects.get_or_create(prefisso=prefisso, anno=anno)
    contatore = ContatoreRichieste.objects.select_for_update().get(prefisso=prefisso, anno=anno)
    contatore.ultimo += 1
    contatore.save(update_fields=["ultimo"])
    return f"{prefisso}-{anno}-{contatore.ultimo:04d}"


def _evento(richiesta: R, a: Attore, azione: str, *, prima: str = "", dopo: str = "", nota: str = "") -> None:
    RichiestaEvento.objects.create(richiesta=richiesta, utente=a.user, utente_nome=a.nome[:160], azione=azione,
                                   prima=prima[:160], dopo=dopo[:160], nota=nota)


@transaction.atomic
def crea(a: Attore, *, tipo: str, persona_id: int, mansione_id=None, competenza_id=None, livello: str = "",
         motivazione: str = "") -> R:
    motivazione = (motivazione or "").strip()
    livello = (livello or "").strip().upper()
    if tipo not in dict(R.TIPO_CHOICES):
        raise RichiestaNonValida("Scegli il tipo di richiesta.")
    if not persona_id or persona_id not in in_forza():
        raise RichiestaNonValida("Scegli la persona.")
    if tipo not in tipi_ammessi(a, persona_id):
        raise RichiestaNonValida("Non puoi aprire questo tipo di richiesta per questa persona.")

    mansione = competenza = None
    if tipo in R.TIPI_MANSIONE:
        mansione = CompetenzaSkm.objects.filter(pk=mansione_id, tipo__in=mstr.TIPI_MANSIONE, attiva=True).first()
        if mansione is None:
            raise RichiestaNonValida("Scegli la mansione.")
        ab = abilitazione(mansione, persona_id)
        if tipo == R.TIPO_AGGIUNTA:
            if livello not in LIVELLI:
                raise RichiestaNonValida("Scegli il livello da raggiungere.")
            if ab is not None and ab.stato == AbilitazioneMacchina.STATO_ATTIVA \
                    and ordinale_livello(ab.livello) >= ordinale_livello(livello):
                raise RichiestaNonValida(f"La persona ha già la mansione a livello {ab.livello}.")
        else:
            livello = ""
            if ab is None:
                raise RichiestaNonValida("La persona non ha questa mansione.")
            if tipo == R.TIPO_SOSPENSIONE and ab.stato == AbilitazioneMacchina.STATO_SOSPESA:
                raise RichiestaNonValida("La mansione è già sospesa.")
            if not motivazione:
                raise RichiestaNonValida("Per sospendere o rimuovere una mansione serve la motivazione.")
    else:
        competenza = CompetenzaCatalogo.objects.filter(pk=competenza_id, attiva=True).first()
        if competenza is None:
            raise RichiestaNonValida("Scegli la competenza.")
        if livello not in LIVELLI:
            raise RichiestaNonValida("Scegli il livello da raggiungere.")

    doppia = R.objects.filter(legacy_anagrafica_id=persona_id, tipo=tipo, mansione=mansione, competenza=competenza,
                              stato__in=R.STATI_APERTI).first()
    if doppia is not None:
        raise RichiestaNonValida(f"C'è già una richiesta aperta uguale: {doppia.codice}.")

    richiesta = R.objects.create(
        codice=_nuovo_codice(tipo), tipo=tipo, legacy_anagrafica_id=persona_id, mansione=mansione,
        competenza=competenza, livello=livello, motivazione=motivazione, richiedente=a.user,
        richiedente_legacy_id=a.legacy_id, richiedente_nome=a.nome[:160],
    )
    _evento(richiesta, a, "Richiesta creata", dopo=richiesta.get_stato_display(), nota=motivazione)
    return richiesta


# ═══════════════════════════════════════════════════════════════════════════
# Decidere
# ═══════════════════════════════════════════════════════════════════════════

def sigla_approva(richiesta: R) -> str:
    return SIGLA_APPROVA[richiesta.tipo]


def motivo_non_decide(a: Attore, richiesta: R) -> str:
    """Perché questo attore non può approvare o respingere; '' se può."""
    if richiesta.stato != R.STATO_IN_APPROVAZIONE:
        return "La richiesta non è più in approvazione."
    sigla = sigla_approva(richiesta)
    if not a.ha(sigla):
        return f"Approva chi ha il ruolo {sigla}."
    if richiesta.richiedente_id == a.user.pk or (a.legacy_id and richiesta.richiedente_legacy_id == a.legacy_id):
        return "Nessuno approva la propria richiesta: serve un altro titolare del ruolo."
    return ""


def _applica(richiesta: R, a: Attore) -> None:
    """Effetto dell'approvazione sulla skill matrix."""
    if richiesta.tipo == R.TIPO_COMPETENZA:
        return
    ab = abilitazione(richiesta.mansione, richiesta.legacy_anagrafica_id)
    if richiesta.tipo == R.TIPO_AGGIUNTA:
        if ab is None:
            mstr.assegna(richiesta.mansione, legacy_anagrafica_id=richiesta.legacy_anagrafica_id,
                         livello=LivelloSkm.IN_FORMAZIONE, user=a.user)
            _evento(richiesta, a, "Skill matrix: mansione in formazione", prima="non assegnata", dopo="I")
        return
    if ab is None:
        raise RichiestaNonValida("La persona non ha più questa mansione: la richiesta va respinta.")
    oggi = timezone.localdate()
    if richiesta.tipo == R.TIPO_SOSPENSIONE:
        prima = ab.get_stato_display()
        ab.stato = AbilitazioneMacchina.STATO_SOSPESA
        ab.save(update_fields=["stato", "updated_at"])
        AbilitazioneMacchinaStorico.objects.create(
            legacy_anagrafica_id=ab.legacy_anagrafica_id, asset_id=ab.asset_id, competenza_id=ab.competenza_id,
            livello=ab.livello, data_rilevazione=oggi, fonte=AbilitazioneMacchinaStorico.FONTE_MANUALE,
            note=f"Sospesa con richiesta {richiesta.codice}"[:255],
        )
        _evento(richiesta, a, "Skill matrix: mansione sospesa", prima=prima, dopo="Sospesa")
    else:
        prima = f"livello {ab.livello or '—'}"
        mstr.togli(ab)
        _evento(richiesta, a, "Skill matrix: mansione rimossa", prima=prima, dopo="rimossa")


@transaction.atomic
def decidi(a: Attore, richiesta: R, *, approva: bool, nota: str = "") -> R:
    richiesta = R.objects.select_for_update().get(pk=richiesta.pk)
    motivo = motivo_non_decide(a, richiesta)
    if motivo:
        raise RichiestaNonValida(motivo)
    nota = (nota or "").strip()
    if not approva and not nota:
        raise RichiestaNonValida("Per respingere scrivi il motivo.")
    prima = richiesta.get_stato_display()
    adesso = timezone.now()
    richiesta.deciso_da, richiesta.deciso_da_nome = a.user, a.nome[:160]
    richiesta.decisa_il, richiesta.nota_decisione = adesso, nota
    if approva:
        richiesta.stato = R.STATO_APPROVATA
        _applica(richiesta, a)
        if richiesta.senza_sessione:
            richiesta.stato, richiesta.evasa_il = R.STATO_EVASA, adesso
    else:
        richiesta.stato = R.STATO_RESPINTA
    richiesta.save()
    _evento(richiesta, a, "Richiesta approvata" if approva else "Richiesta respinta", prima=prima,
            dopo=richiesta.get_stato_display(), nota=nota)
    return richiesta


# ═══════════════════════════════════════════════════════════════════════════
# Vedere
# ═══════════════════════════════════════════════════════════════════════════

def puo_vedere(a: Attore, richiesta: R) -> bool:
    return bool(a.gestione or a.ha(sigla_approva(richiesta)) or richiesta.richiedente_id == a.user.pk
                or richiesta.legacy_anagrafica_id in a.team
                or (a.legacy_id and richiesta.legacy_anagrafica_id == a.legacy_id))


def visibili(a: Attore):
    qs = R.objects.select_related("mansione", "competenza")
    if a.gestione:
        return qs
    filtro = Q(richiedente=a.user)
    if a.team:
        filtro |= Q(legacy_anagrafica_id__in=a.team)
    if a.legacy_id:
        filtro |= Q(legacy_anagrafica_id=a.legacy_id)
    tipi = [t for t, s in SIGLA_APPROVA.items() if a.ha(s)]
    if tipi:
        filtro |= Q(tipo__in=tipi)
    return qs.filter(filtro)


def tocca_a(richiesta: R) -> str:
    """A chi tocca il prossimo passo, in parole."""
    if richiesta.stato == R.STATO_IN_APPROVAZIONE:
        return f"{sigla_approva(richiesta)}: approvare"
    if richiesta.stato == R.STATO_APPROVATA:
        return "Qualità o HR: aprire la sessione formativa"
    return ""


def righe(richieste) -> list[dict]:
    """Le richieste con nome della persona e prossimo passo, pronte per un elenco."""
    richieste = list(richieste)
    nomi = struttura_vista._nomi(sorted({r.legacy_anagrafica_id for r in richieste}))
    oggi = timezone.localdate()
    return [{"richiesta": r, "persona": nomi.get(r.legacy_anagrafica_id) or f"#{r.legacy_anagrafica_id}",
             "tocca_a": tocca_a(r), "giorni": (oggi - timezone.localtime(r.creata_il).date()).days} for r in richieste]


def da_fare(a: Attore) -> dict:
    """Che cosa aspetta questo attore e che cosa, di suo, aspetta gli altri."""
    tipi = [t for t, s in SIGLA_APPROVA.items() if a.ha(s)]
    da_approvare = []
    if tipi:
        qs = R.objects.select_related("mansione", "competenza").filter(stato=R.STATO_IN_APPROVAZIONE, tipo__in=tipi)
        da_approvare = [r for r in qs.order_by("creata_il") if not motivo_non_decide(a, r)]
    in_attesa = (R.objects.select_related("mansione", "competenza")
                 .filter(richiedente=a.user, stato__in=R.STATI_APERTI).order_by("creata_il"))
    return {"da_approvare": righe(da_approvare), "in_attesa": righe(in_attesa)}


def conta_da_fare(a: Attore) -> int:
    return len(da_fare(a)["da_approvare"])


def fabbisogno(richiesta: R) -> list[dict]:
    """Per un'assegnazione: le competenze della mansione, il livello richiesto e quello di oggi."""
    from .esplora_semplice import livello as lv

    if richiesta.tipo != R.TIPO_AGGIUNTA or richiesta.mansione_id is None:
        return []
    ab = abilitazione(richiesta.mansione, richiesta.legacy_anagrafica_id)
    suoi = {v.voce_id: v.livello for v in ab.voci.all()} if ab is not None else {}
    altrove = competenze_catalogo.livelli_noti(richiesta.legacy_anagrafica_id)
    out = []
    for voce in mc.competenze(richiesta.mansione):
        oggi = suoi.get(voce.pk) or (altrove.get(voce.catalogo_id) or {}).get("livello") or ""
        presente = ordinale_livello(oggi) >= ordinale_livello(voce.livello_minimo)
        out.append({"nome": voce.nome, "richiesto": lv(voce.livello_minimo), "oggi": lv(oggi), "presente": presente})
    return out


def passi(richiesta: R) -> list[dict]:
    """La fila dei passi con quello corrente, per la testata della richiesta."""
    sigla = sigla_approva(richiesta)
    firma = "RDD, poi la persona" if richiesta.su_mansione else "MSO, poi la persona"
    if richiesta.senza_sessione:
        nomi = [("Richiesta", richiesta.richiedente_nome), ("Approvazione", f"Tocca a {sigla}"),
                ("Skill matrix aggiornata", "Senza sessione formativa")]
        corrente = {R.STATO_IN_APPROVAZIONE: 1, R.STATO_RESPINTA: 1}.get(richiesta.stato, 3)
    else:
        nomi = [("Richiesta", richiesta.richiedente_nome), ("Approvazione", f"Tocca a {sigla}"),
                ("Formazione", "Apre la Qualità o HR"), ("Firme di chiusura", firma),
                ("Chiusa", "Livello nella skill matrix")]
        corrente = {R.STATO_IN_APPROVAZIONE: 1, R.STATO_RESPINTA: 1, R.STATO_APPROVATA: 2}.get(richiesta.stato, 5)
    out = []
    for i, (nome, sotto) in enumerate(nomi):
        stato = "fatto" if i < corrente else "ora" if i == corrente else ""
        if i == 1 and richiesta.stato == R.STATO_RESPINTA:
            stato, sotto = "respinta", f"Respinta da {richiesta.deciso_da_nome}"
        elif i == 1 and richiesta.decisa_il:
            sotto = f"{richiesta.deciso_da_nome}, {timezone.localtime(richiesta.decisa_il):%d/%m/%Y}"
        elif i == 0:
            sotto = f"{sotto}, {timezone.localtime(richiesta.creata_il):%d/%m/%Y}"
        out.append({"nome": nome, "sotto": sotto, "stato": stato})
    return out
