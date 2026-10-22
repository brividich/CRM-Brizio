"""Caricamento della struttura della Qualità (MEGA SKILL MATRIX v8) nel portale.

Applica il file della Qualità e le decisioni del 21/10/2026 (``struttura_v8_dati``)
in un ordine che non perde informazioni:

1. reparti e aree (rinomine, aree nuove, aree che confluiscono: le persone passano);
2. area delle persone che non ce l'hanno, ricavata dal ruolo di **oggi** (va fatto
   prima dell'accorpamento dei ruoli, che quel ruolo lo chiude);
3. ruoli: sigla, diretto/indiretto, rinomine, accorpamenti (permessi e collegamenti
   passano al ruolo della struttura, nessuno perde accessi), ruoli da spegnere;
4. responsabili di reparti e aree (ruolo) e caporeparto dei reparti nuovi;
5. processi SGI con owner e tipo (con la revisione del registro);
6. mansioni: rinomine 1:1, mansioni nuove, area/ruolo/processo/abilitazione,
   divisioni (la vecchia si spegne, le nuove partono «da valutare»);
7. «Responsabilità del reparto» generate dal ruolo responsabile;
8. mansioni di rischio **proposte** (valgono solo dopo la conferma HSE).

Gira sempre dentro una transazione: in prova (``applica=False``) alla fine si
annulla tutto e resta solo il rapporto. Idempotente: un secondo giro non cambia
niente. Non cancella nulla.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from django.db import transaction

from .. import struttura_v8_dati as V8
from ..models import (
    AmbitoRuolo,
    AreaAziendale,
    CompetenzaSkm,
    DipendenteAnagraficaAziendale,
    DipendenteRuoloOperativo,
    Reparto,
    RuoloOperativo,
)
from . import mansionario_struttura as mstr
from . import struttura_aree, struttura_rischi, struttura_ruoli

RESPONSABILITA = "Responsabilità del reparto"


@dataclass
class Riga:
    fase: str
    azione: str      # crea, rinomina, aggiorna, accorpa, sposta, spegne, segnala
    oggetto: str
    dettaglio: str = ""


@dataclass
class Rapporto:
    applicato: bool = False
    righe: list[Riga] = field(default_factory=list)

    def add(self, fase, azione, oggetto, dettaglio=""):
        self.righe.append(Riga(fase, azione, str(oggetto), dettaglio))

    def conteggi(self) -> dict:
        return dict(Counter(f"{r.fase}:{r.azione}" for r in self.righe))

    @property
    def da_decidere(self) -> list[Riga]:
        return [r for r in self.righe if r.azione == "segnala"]


def _norm(testo: str) -> str:
    return " ".join((testo or "").split()).casefold()


# ═══════════════════════════════════════════════════════════════════════════
# 1. Reparti e aree
# ═══════════════════════════════════════════════════════════════════════════

def _area(nome: str) -> AreaAziendale | None:
    return AreaAziendale.objects.filter(nome__iexact=(nome or "").strip()).select_related("reparto").first()


def _reparti_aree(r: Rapporto, user) -> dict[str, Reparto]:
    reparti: dict[str, Reparto] = {}
    for nome, (rinomina_da, _resp) in V8.REPARTI.items():
        rep = Reparto.objects.filter(nome__iexact=nome).first()
        if rep is None and rinomina_da:
            vecchio = Reparto.objects.filter(nome__iexact=rinomina_da).first()
            if vecchio is not None:
                esito = struttura_aree.rinomina_reparto(vecchio, nome, user=user)
                r.add("reparti", "rinomina", nome, f"era «{rinomina_da}» ({esito['schede']} schede, "
                                                   f"{esito['legacy']} righe anagrafica)")
                rep = vecchio
        if rep is None:
            rep = Reparto.objects.create(nome=nome)
            r.add("reparti", "crea", nome)
        if not rep.is_active:
            rep.is_active = True
            rep.save(update_fields=["is_active"])
            r.add("reparti", "aggiorna", nome, "riattivato")
        reparti[nome] = rep

    for nome, (rep_nome, fonti, _resp) in V8.AREE.items():
        rep = reparti[rep_nome]
        ospite = _area(nome)
        sorgenti = [a for a in (_area(f) for f in fonti) if a is not None]
        if ospite is None and sorgenti:
            ospite = sorgenti[0]
            prima = ospite.nome
            ospite.nome = nome
            ospite.save(update_fields=["nome"])
            r.add("aree", "rinomina", nome, f"era «{prima}»")
        if ospite is None:
            ospite = AreaAziendale.objects.create(nome=nome, reparto=rep)
            r.add("aree", "crea", nome, f"nel reparto {rep.nome}")
        campi = []
        if ospite.nome != nome:  # stessa area, nome diverso solo per maiuscole: si allinea al file
            r.add("aree", "rinomina", nome, f"era «{ospite.nome}»")
            ospite.nome = nome
            campi.append("nome")
        if ospite.reparto_id != rep.pk:
            r.add("aree", "aggiorna", nome, f"reparto {ospite.reparto.nome if ospite.reparto_id else '—'} -> {rep.nome}")
            ospite.reparto = rep
            campi.append("reparto")
        if not ospite.is_active:
            ospite.is_active = True
            campi.append("is_active")
        if campi:
            ospite.save(update_fields=campi)
        # Chi è già nell'area ma risulta in un altro reparto segue l'area.
        for lid in list(DipendenteAnagraficaAziendale.objects.filter(area_aziendale=ospite)
                        .exclude(area__iexact=rep.nome).values_list("legacy_anagrafica_id", flat=True)):
            struttura_aree.sposta_persona(lid, ospite, user=user)
            r.add("persone", "sposta", f"#{lid}", f"reparto -> {rep.nome} (area {nome})")
        for src in sorgenti:
            if src.pk == ospite.pk:
                continue
            if not src.is_active and not DipendenteAnagraficaAziendale.objects.filter(area_aziendale=src).exists() \
                    and not CompetenzaSkm.objects.filter(area=src).exists():
                continue  # già accorpata in un giro precedente
            n = struttura_aree.accorpa_area(src, ospite, user=user)
            r.add("aree", "accorpa", src.nome, f"in {nome}: {n} persone spostate, area spenta")

    nomi_v8 = {_norm(n) for n in V8.AREE}
    for a in AreaAziendale.objects.filter(is_active=True).select_related("reparto"):
        if _norm(a.nome) not in nomi_v8:
            r.add("aree", "segnala", a.nome, "area attiva fuori dalla struttura v8: decidere se tenerla")
    return reparti


# ═══════════════════════════════════════════════════════════════════════════
# 2. Area delle persone dal ruolo di oggi
# ═══════════════════════════════════════════════════════════════════════════

def _persone_attive() -> set[int]:
    from core.legacy_anagrafica import fetch_anagrafica_rows

    return {int(x["id"]) for x in fetch_anagrafica_rows(deduplicate=True) if x.get("id") and x.get("attivo", True)}


def _ruoli_in_essere_per_persona() -> dict[int, list[DipendenteRuoloOperativo]]:
    from django.db.models import Q
    from django.utils import timezone

    oggi = timezone.localdate()
    out: dict[int, list] = {}
    for a in (DipendenteRuoloOperativo.objects.filter(Q(data_fine__isnull=True) | Q(data_fine__gte=oggi))
              .select_related("ruolo")):
        out.setdefault(a.legacy_anagrafica_id, []).append(a)
    for lista in out.values():
        lista.sort(key=lambda a: (a.tipologia != DipendenteRuoloOperativo.TIPOLOGIA_PRINCIPALE, a.ruolo.nome))
    return out


def _aree_persone(r: Rapporto, user) -> dict[str, list[int]]:
    """Area dal ruolo di oggi per chi non ne ha una; ritorna i candidati caporeparto."""
    attive = _persone_attive()
    per_persona = _ruoli_in_essere_per_persona()
    aree_attuali = dict(DipendenteAnagraficaAziendale.objects.values_list("legacy_anagrafica_id", "area_aziendale_id"))
    capi: dict[str, list[int]] = {}
    for rep, ruoli in V8.CAPO_DA_RUOLO.items():
        nomi = {_norm(n) for n in ruoli}
        capi[rep] = sorted({lid for lid, lista in per_persona.items() if lid in attive
                            for a in lista if _norm(a.ruolo.nome) in nomi})
    for lid, lista in sorted(per_persona.items()):
        if lid not in attive:
            continue
        destinazione = next((V8.AREA_DA_RUOLO[a.ruolo.nome] for a in lista if a.ruolo.nome in V8.AREA_DA_RUOLO), None)
        if destinazione is None:
            # Ruoli di posizione: l'area è quella del ruolo nella struttura.
            for a in lista:
                v8 = next((k for k, v in V8.RUOLI.items() if v[3] and _norm(v[3]) == _norm(a.ruolo.nome)), None)
                area_v8 = next((riga[4] for riga in V8.RIGHE if riga[3] == v8 and not riga[6]), None) if v8 else None
                if area_v8:
                    destinazione = area_v8
                    break
        if destinazione is None:
            continue
        area = _area(destinazione)
        if area is None:
            continue
        if aree_attuali.get(lid):
            if aree_attuali[lid] != area.pk:
                r.add("persone", "segnala", f"#{lid}",
                      f"ha già un'area; dal ruolo «{lista[0].ruolo.nome}» sarebbe {destinazione}: non toccata")
            continue
        struttura_aree.sposta_persona(lid, area, user=user)
        r.add("persone", "sposta", f"#{lid}", f"area {destinazione} (dal ruolo «{lista[0].ruolo.nome}»)")
    return capi


# ═══════════════════════════════════════════════════════════════════════════
# 3. Ruoli
# ═══════════════════════════════════════════════════════════════════════════

def _ruolo(nome: str) -> RuoloOperativo | None:
    return RuoloOperativo.objects.filter(nome__iexact=(nome or "").strip()).first()


def _ruoli(r: Rapporto, user) -> dict[str, RuoloOperativo]:
    ambito = (AmbitoRuolo.objects.filter(nome__iexact=V8.AMBITO_STRUTTURA).first()
              or AmbitoRuolo.objects.filter(alimenta_scheda=True).first())
    per_v8: dict[str, RuoloOperativo] = {}
    for chiave, (sigla, nome, classe, ospite_nome, accorpati) in V8.RUOLI.items():
        ruolo = (RuoloOperativo.objects.filter(sigla=sigla).first() if sigla else None) or _ruolo(nome)
        if ruolo is None and ospite_nome:
            ruolo = _ruolo(ospite_nome)
        if ruolo is None:
            ruolo = RuoloOperativo.objects.create(nome=nome, sigla=sigla, classe=classe, ambito=ambito)
            r.add("ruoli", "crea", ruolo.etichetta, "nessun ruolo di oggi corrisponde: da assegnare a mano")
        else:
            if ruolo.nome != nome:
                prima = ruolo.nome
                esito = struttura_ruoli.rinomina(ruolo, nome, user=user)
                r.add("ruoli", "rinomina", nome, f"era «{prima}» ({esito['schede']} schede)")
            cambi = []
            if (ruolo.sigla or None) != (sigla or None):
                ruolo.sigla = sigla
                cambi.append(f"sigla {sigla}")
            if ruolo.classe != classe:
                ruolo.classe = classe
                cambi.append(classe.lower())
            if ambito and ruolo.ambito_id != ambito.pk:
                cambi.append(f"organigramma {ruolo.ambito_label} -> {ambito.nome}")
                ruolo.ambito = ambito
            if not ruolo.is_active:
                ruolo.is_active = True
                cambi.append("riattivato")
            if cambi:
                ruolo.save()
                r.add("ruoli", "aggiorna", ruolo.etichetta, ", ".join(cambi))
        for vecchio_nome in accorpati:
            vecchio = _ruolo(vecchio_nome)
            if vecchio is None or vecchio.pk == ruolo.pk:
                continue
            if not vecchio.is_active and not vecchio.assegnazioni.filter(data_fine__isnull=True).exists():
                continue  # già accorpato in un giro precedente
            esito = struttura_ruoli.accorpa(vecchio, ruolo, user=user)
            r.add("ruoli", "accorpa", vecchio_nome, f"in {ruolo.etichetta}: {esito['persone']} persone, "
                                                  f"{esito['profili']} profili permessi, {esito['fk'] + esito['m2m']} collegamenti")
        per_v8[chiave] = ruolo
    for nome in V8.RUOLI_DA_SPEGNERE:
        ruolo = _ruolo(nome)
        if ruolo is None or not ruolo.is_active:
            continue
        if ruolo.assegnazioni.filter(data_fine__isnull=True).exists():
            r.add("ruoli", "segnala", nome, "da spegnere ma qualcuno lo ricopre: lasciato acceso")
            continue
        ruolo.is_active = False
        ruolo.save(update_fields=["is_active"])
        r.add("ruoli", "spegne", nome)
    for nome, ambito_nome in V8.RUOLI_AMBITO.items():
        ruolo, amb = _ruolo(nome), AmbitoRuolo.objects.filter(nome__iexact=ambito_nome).first()
        if ruolo and amb and ruolo.ambito_id != amb.pk:
            ruolo.ambito = amb
            ruolo.save(update_fields=["ambito"])
            r.add("ruoli", "aggiorna", nome, f"organigramma -> {amb.nome}")
    return per_v8


# ═══════════════════════════════════════════════════════════════════════════
# 4. Responsabili
# ═══════════════════════════════════════════════════════════════════════════

def _responsabili(r: Rapporto, reparti, ruoli, capi, user) -> None:
    def per_sigla(s):
        return ruoli.get(s) if s else None

    for nome, (_x, resp) in V8.REPARTI.items():
        rep, ruolo = reparti[nome], per_sigla(resp)
        if ruolo and rep.ruolo_responsabile_id != ruolo.pk:
            rep.ruolo_responsabile = ruolo
            rep.save(update_fields=["ruolo_responsabile"])
            r.add("reparti", "aggiorna", nome, f"ruolo responsabile {ruolo.etichetta}")
    for nome, (_rep, _fonti, resp) in V8.AREE.items():
        area, ruolo = _area(nome), per_sigla(resp)
        if area and ruolo and area.ruolo_responsabile_id != ruolo.pk:
            area.ruolo_responsabile = ruolo
            area.save(update_fields=["ruolo_responsabile"])
            r.add("aree", "aggiorna", nome, f"ruolo responsabile {ruolo.etichetta}")
    for nome, candidati in capi.items():
        rep = reparti.get(nome)
        if rep is None or rep.caporeparto_legacy_id or not candidati:
            continue
        if len(candidati) == 1:
            rep.caporeparto_legacy_id = candidati[0]
            rep.save(update_fields=["caporeparto_legacy_id"])
            from ..views.struttura import _sync_reparto_capo_mapping
            from .reparto_canonico import riallinea_capo_schede

            _sync_reparto_capo_mapping(rep)
            riallinea_capo_schede(reparto=rep)
            r.add("reparti", "aggiorna", nome, f"caporeparto #{candidati[0]}")
        else:
            rep.responsabili.add(*candidati)
            r.add("reparti", "segnala", nome, f"{len(candidati)} caporeparto possibili ("
                                             + ", ".join(f"#{c}" for c in candidati)
                                             + "): messi fra i responsabili, scegliere il caporeparto")


# ═══════════════════════════════════════════════════════════════════════════
# 5. Processi SGI
# ═══════════════════════════════════════════════════════════════════════════

def _processi(r: Rapporto, ruoli, user) -> dict:
    from sistema_gestione.models import Processo
    from sistema_gestione.services.processi import salva_processo

    out = {}
    for nome, (codice, categoria, tipo, owner) in V8.PROCESSI.items():
        p = Processo.objects.filter(codice=codice).first() or Processo.objects.filter(nome__iexact=nome).first()
        ruolo = ruoli.get(owner)
        if p is None:
            p = Processo(codice=codice, nome=nome, categoria=categoria, tipo=tipo, ruolo_owner=ruolo)
            salva_processo(p, motivo="Prima emissione dalla struttura della Qualità (MEGA SKILL MATRIX v8)",
                           user=user, nuovo=True)
            r.add("processi", "crea", f"{codice} {nome}", f"{tipo.lower()}, owner {ruolo.etichetta if ruolo else '—'}")
        else:
            cambi = []
            if p.tipo != tipo:
                p.tipo, cambi = tipo, cambi + [f"tipo {tipo.lower()}"]
            if ruolo and p.ruolo_owner_id != ruolo.pk:
                p.ruolo_owner, cambi = ruolo, cambi + [f"owner {ruolo.etichetta}"]
            if cambi:
                salva_processo(p, motivo="Allineamento alla struttura della Qualità (v8): " + ", ".join(cambi),
                               user=user)
                r.add("processi", "aggiorna", f"{p.codice} {p.nome}", ", ".join(cambi))
        out[nome] = p
    return out


# ═══════════════════════════════════════════════════════════════════════════
# 6. Mansioni
# ═══════════════════════════════════════════════════════════════════════════

class _Indice:
    def __init__(self):
        self.per_nome: dict[str, CompetenzaSkm] = {}
        for m in CompetenzaSkm.objects.filter(tipo__in=mstr.TIPI_MANSIONE).order_by("-attiva", "pk"):
            self.metti(m)

    def metti(self, m: CompetenzaSkm):
        for n in [m.display, m.competenza_key, *mstr.nomi_precedenti(m)]:
            if n:
                self.per_nome.setdefault(_norm(n), m)

    def trova(self, nome: str) -> CompetenzaSkm | None:
        return self.per_nome.get(_norm(nome))


_CODICE_MACCHINA = re.compile(r"^([A-Z0-9]{1,6}) - ")


def _asset_per_codice(codice: str):
    from assets.models import Asset

    pattern = re.compile(rf"(?<![A-Z0-9]){re.escape(codice.upper())}(?![0-9])")
    trovati = [a for a in Asset.objects.filter(asset_tag__icontains=codice).only("id", "asset_tag", "name")
               if pattern.search((a.asset_tag or "").upper())]
    if not trovati:
        trovati = [a for a in Asset.objects.filter(name__icontains=codice).only("id", "asset_tag", "name")
                   if pattern.search((a.name or "").upper())]
    return trovati[0] if len(trovati) == 1 else None


def _mansioni(r: Rapporto, ruoli, processi, user) -> None:
    idx = _Indice()
    for vecchio, nuovo in V8.MANSIONI_RINOMINA.items():
        m = idx.trova(vecchio)
        if m is not None and idx.trova(nuovo) in (None, m) and _norm(m.nome) != _norm(nuovo):
            mstr.rinomina(m, nuovo)
            idx.metti(m)
            r.add("mansioni", "rinomina", nuovo, f"era «{vecchio}»: livelli e storico restano")

    figli = {_norm(f): v for v, lista in V8.MANSIONI_DIVISE.items() for f in lista}
    viste: set[int] = set()
    for processo, _owner, _dir, ruolo_v8, area_nome, nome, responsabile, abilitazione in V8.RIGHE:
        if responsabile:
            continue  # «Responsabilità del reparto»: fase 7, dal ruolo responsabile del reparto
        m = idx.trova(nome)
        if m is None:
            codice = _CODICE_MACCHINA.match(nome)
            asset = _asset_per_codice(codice.group(1)) if codice else None
            if asset is not None and not CompetenzaSkm.objects.filter(competenza_key=codice.group(1)).exists():
                m = CompetenzaSkm.objects.create(competenza_key=codice.group(1), display=nome,
                                                 tipo=CompetenzaSkm.TIPO_MACCHINA, asset=asset,
                                                 match_confidenza=CompetenzaSkm.CONF_ESATTO,
                                                 match_strategia="struttura_v8", match_confermato=True)
                r.add("mansioni", "crea", nome, f"macchina, collegata all'asset {asset.asset_tag}")
            else:
                m = mstr.crea_processo(nome)
                r.add("mansioni", "crea", nome, "nuova")
            idx.metti(m)
        area = _area(area_nome)
        ruolo = ruoli.get(ruolo_v8)
        cambi = []
        if area is not None and m.area_id != area.pk:
            m.area = area
            cambi.append(f"area {area.nome}")
        p = processi.get(processo)
        if p is not None and m.processo_sgi_id != p.pk:
            m.processo_sgi = p
            cambi.append(f"processo {p.nome}")
        if m.abilitazione_con_scadenza != abilitazione:
            m.abilitazione_con_scadenza = abilitazione
            cambi.append("abilitazione con validità" if abilitazione else "senza abilitazione")
        if not m.attiva:
            m.attiva = True
            cambi.append("riattivata")
        madre = idx.trova(figli[_norm(nome)]) if _norm(nome) in figli else None
        if madre is not None and madre.pk != m.pk and m.deriva_da_id != madre.pk:
            m.deriva_da = madre
            cambi.append(f"deriva da «{madre.nome}»")
        if cambi:
            m.save()
        if ruolo is not None and set(m.ruoli.values_list("pk", flat=True)) != {ruolo.pk}:
            m.ruoli.set([ruolo])
            cambi.append(f"ruolo {ruolo.etichetta}")
        if cambi:
            r.add("mansioni", "aggiorna", m.nome, ", ".join(cambi))
        viste.add(m.pk)

    for vecchio in V8.MANSIONI_DIVISE:
        m = idx.trova(vecchio)
        if m is not None and m.pk not in viste and m.attiva:
            m.attiva = False
            m.save(update_fields=["attiva", "updated_at"])
            r.add("mansioni", "spegne", m.nome, "divisa nelle mansioni nuove: i livelli restano come suggerimento")
    sospese = {_norm(n) for n in V8.MANSIONI_IN_SOSPESO}
    for m in CompetenzaSkm.objects.filter(tipo__in=mstr.TIPI_MANSIONE, attiva=True, responsabilita_reparto__isnull=True):
        if m.pk in viste:
            continue
        motivo = "in sospeso: decide la Qualità" if _norm(m.nome) in sospese else "non è nel file v8"
        r.add("mansioni", "segnala", m.nome, motivo + " (lasciata com'è)")


# ═══════════════════════════════════════════════════════════════════════════
# 7. Responsabilità del reparto
# ═══════════════════════════════════════════════════════════════════════════

def assicura_responsabilita(reparto: Reparto, processo=None) -> tuple[CompetenzaSkm | None, bool]:
    """La mansione «Responsabilità del reparto» segue il ruolo responsabile del reparto.

    Una per reparto; si spegne (non si cancella) se il reparto non ha più un ruolo
    responsabile o è spento. Ritorna (mansione, cambiata).
    """
    m = CompetenzaSkm.objects.filter(responsabilita_reparto=reparto).first()
    attiva = bool(reparto.ruolo_responsabile_id and reparto.is_active)
    if m is None and not attiva:
        return None, False
    nome = f"{RESPONSABILITA} {reparto.nome}"
    cambiata = False
    if m is None:
        altro = CompetenzaSkm.objects.filter(tipo__in=mstr.TIPI_MANSIONE, display__iexact=nome).first()
        m = altro or CompetenzaSkm(competenza_key=mstr.chiave_nuova(nome), display=nome,
                                   tipo=CompetenzaSkm.TIPO_PROCESSO)
        m.responsabilita_reparto = reparto
        cambiata = True
    if m.display != nome:
        mstr.rinomina(m, nome, salva=False)
        cambiata = True
    if m.reparto_id != reparto.pk or m.attiva != attiva:
        m.reparto, m.attiva, cambiata = reparto, attiva, True
    if processo is not None and m.processo_sgi_id != processo.pk:
        m.processo_sgi, cambiata = processo, True
    if cambiata:
        m.save()
    if attiva and set(m.ruoli.values_list("pk", flat=True)) != {reparto.ruolo_responsabile_id}:
        m.ruoli.set([reparto.ruolo_responsabile_id])
        cambiata = True
    return m, cambiata


def _responsabilita(r: Rapporto, reparti, processi) -> None:
    # Processo della responsabilità: quello delle righe RESPONSABILE=Y del file per le aree del reparto.
    proc_per_reparto = {}
    for processo, *_x, area_nome, _nome, responsabile, _ab in V8.RIGHE:
        if responsabile and area_nome in V8.AREE:
            proc_per_reparto.setdefault(V8.AREE[area_nome][0], processo)
    for nome, rep in reparti.items():
        rep.refresh_from_db()
        m, cambiata = assicura_responsabilita(rep, processi.get(proc_per_reparto.get(nome)))
        if cambiata and m is not None:
            r.add("mansioni", "crea" if m.attiva else "spegne", m.nome,
                  f"ruolo {rep.ruolo_responsabile.etichetta}" if rep.ruolo_responsabile_id else "")


# ═══════════════════════════════════════════════════════════════════════════
# Orchestrazione
# ═══════════════════════════════════════════════════════════════════════════

def carica(*, applica: bool = False, user=None, aree_persone: bool = True) -> Rapporto:
    r = Rapporto()
    with transaction.atomic():
        reparti = _reparti_aree(r, user)
        capi = _aree_persone(r, user) if aree_persone else {}
        ruoli = _ruoli(r, user)
        _responsabili(r, reparti, ruoli, capi, user)
        processi = _processi(r, ruoli, user)
        _mansioni(r, ruoli, processi, user)
        _responsabilita(r, reparti, processi)
        n = struttura_rischi.proponi()
        if n:
            r.add("rischi", "aggiorna", f"{n} mansioni", "mansione di rischio proposta: va confermata da HSE")
        if not applica:
            transaction.set_rollback(True)
    r.applicato = applica
    return r
