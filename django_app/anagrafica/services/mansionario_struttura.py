"""Mansionario: ruolo → mansione (macchina o processo) → persone.

Spec ``docs/superpowers/specs/2026-10-15-mansionario-ruolo-mansione-competenze-rischio-design.md``,
fase 2. La mansione è una colonna della skill matrix MOD.187 (``CompetenzaSkm``
di tipo macchina o processo, il «contatore» non è una mansione). Ha uno o più
ruoli, le mansioni di rischio che comporta (catalogo ``Mansione``) e un reparto:
quello dell'asset per le macchine, scelto per i processi.

Le persone sono le abilitazioni «in lista» sulla colonna (``AbilitazioneMacchina``,
legata alla colonna da ``competenza``; per le macchine vale anche l'asset).
Nessun dato sanitario: qui ci sono solo livelli di esperienza I/L/U/O.
"""
from __future__ import annotations

from collections import Counter

from django.db import transaction
from django.utils import timezone

from ..models import (
    AbilitazioneMacchina,
    AbilitazioneMacchinaStorico,
    CompetenzaSkm,
    LivelloSkm,
    SkillMatrixConfig,
    ordinale_livello,
)

TIPI_MANSIONE = (CompetenzaSkm.TIPO_MACCHINA, CompetenzaSkm.TIPO_PROCESSO)
LIVELLI = [c for c, _ in LivelloSkm.choices]  # I, L, U, O


def mansioni(*, solo_attive: bool = True):
    qs = (
        CompetenzaSkm.objects.filter(tipo__in=TIPI_MANSIONE)
        .select_related("asset", "reparto", "area")
        .prefetch_related("ruoli", "mansioni_rischio")
        .order_by("tipo", "display", "competenza_key")
    )
    return qs.filter(attiva=True) if solo_attive else qs


def _abilitazioni_in_lista(competenze) -> dict[int, list[AbilitazioneMacchina]]:
    ids = [c.pk for c in competenze]
    out: dict[int, list] = {}
    if not ids:
        return out
    for ab in AbilitazioneMacchina.objects.filter(competenza_id__in=ids, in_lista=True):
        out.setdefault(ab.competenza_id, []).append(ab)
    return out


def riepilogo(*, solo_attive: bool = True) -> list[dict]:
    """Una riga per mansione con i conteggi per livello e gli operativi (una query per tutte)."""
    config = SkillMatrixConfig.get_instance()
    soglia = config.soglia_operativa_ordinale
    comps = list(mansioni(solo_attive=solo_attive))
    per_comp = _abilitazioni_in_lista(comps)
    righe = []
    for c in comps:
        abil = per_comp.get(c.pk, [])
        livelli = Counter(a.livello for a in abil)
        operativi = sum(1 for a in abil if a.is_operativa(soglia))
        righe.append({
            "mansione": c,
            "nome": c.nome,
            "tipo": c.tipo,
            "reparto": c.reparto_effettivo,
            "ruoli": list(c.ruoli.all()),
            "rischi": list(c.mansioni_rischio.all()),
            "livelli": {lv: livelli.get(lv, 0) for lv in LIVELLI},
            "in_lista": len(abil),
            "persone_ids": sorted({a.legacy_anagrafica_id for a in abil}),
            "operativi": operativi,
            "uomo_solo": operativi < config.soglia_uomo_solo,
        })
    return righe


def kpi(righe: list[dict]) -> dict:
    return {
        "mansioni": len(righe),
        "senza_ruolo": sum(1 for r in righe if not r["ruoli"]),
        "senza_rischio": sum(1 for r in righe if not r["rischi"]),
        "scoperte": sum(1 for r in righe if not r["operativi"]),
    }


def persone(mansione: CompetenzaSkm) -> list[dict]:
    """Chi è in lista sulla mansione, con livello e stato (nomi dall'anagrafica)."""
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    soglia = SkillMatrixConfig.get_instance().soglia_operativa_ordinale
    abil = list(AbilitazioneMacchina.objects.filter(competenza=mansione, in_lista=True))
    nomi = {int(r["id"]): naming.nome_completo(r.get("nome"), r.get("cognome"))
            for r in fetch_anagrafica_rows(ids=[a.legacy_anagrafica_id for a in abil])} if abil else {}
    out = [{
        "abilitazione": a,
        "legacy_id": a.legacy_anagrafica_id,
        "nome": nomi.get(a.legacy_anagrafica_id) or f"#{a.legacy_anagrafica_id}",
        "livello": a.livello,
        "operativa": a.is_operativa(soglia),
        "sospesa": a.stato == AbilitazioneMacchina.STATO_SOSPESA,
        "data_assegnazione": a.data_assegnazione,
        "prossima_revisione": a.prossima_revisione,
    } for a in abil]
    out.sort(key=lambda p: (-ordinale_livello(p["livello"]), p["nome"].casefold()))
    return out


@transaction.atomic
def salva_configurazione(mansione: CompetenzaSkm, *, ruoli_ids, rischi_ids, reparto_id=None, attiva=True) -> None:
    from ..models import Mansione, Reparto, RuoloOperativo

    mansione.ruoli.set(RuoloOperativo.objects.filter(pk__in=list(ruoli_ids), is_active=True))
    mansione.mansioni_rischio.set(Mansione.objects.filter(pk__in=list(rischi_ids), is_active=True))
    # Il reparto si sceglie solo per i processi senza asset: per le macchine vale l'asset.
    if not mansione.asset_id:
        mansione.reparto = Reparto.objects.filter(pk=reparto_id).first() if reparto_id else None
    mansione.attiva = bool(attiva)
    mansione.save(update_fields=["reparto", "attiva", "updated_at"])


@transaction.atomic
def assegna(mansione: CompetenzaSkm, *, legacy_anagrafica_id: int, livello: str, user=None) -> AbilitazioneMacchina:
    """Mette la persona in lista sulla mansione col livello dato (crea o aggiorna) e lo storicizza."""
    livello = (livello or "").strip().upper()
    if livello not in LIVELLI:
        raise ValueError(f"Livello non valido: {livello!r}")
    from django.db import IntegrityError

    oggi = timezone.localdate()
    chiave = {"asset_id": mansione.asset_id} if mansione.asset_id else {"competenza": mansione}
    righe = AbilitazioneMacchina.objects.select_for_update().filter(legacy_anagrafica_id=legacy_anagrafica_id, **chiave)
    ab = righe.first()
    if ab is None:
        # Doppio invio dello stesso form: chi arriva secondo trova la riga creata
        # dal primo (indice unico persona+mansione) e la aggiorna invece di dare errore.
        try:
            with transaction.atomic():
                ab = AbilitazioneMacchina.objects.create(
                    legacy_anagrafica_id=legacy_anagrafica_id, asset_id=mansione.asset_id,
                    competenza=mansione, data_assegnazione=oggi, livello=livello,
                )
        except IntegrityError:
            ab = righe.first()
            if ab is None:
                raise
    ab.competenza = mansione
    ab.livello = livello
    ab.in_lista = True
    ab.stato = AbilitazioneMacchina.STATO_ATTIVA
    if ab.data_assegnazione is None:
        ab.data_assegnazione = oggi
    ab.save()
    AbilitazioneMacchinaStorico.objects.create(
        legacy_anagrafica_id=legacy_anagrafica_id, asset_id=mansione.asset_id, competenza=mansione,
        livello=livello, data_rilevazione=oggi, fonte=AbilitazioneMacchinaStorico.FONTE_MANUALE,
        note="Mansionario: assegnazione",
    )
    return ab


@transaction.atomic
def togli(abilitazione: AbilitazioneMacchina) -> None:
    """Toglie la persona dalla lista della mansione (la riga resta, con lo storico)."""
    if not abilitazione.in_lista:
        return  # già fuori lista (doppio clic): nessuno scatto doppio nello storico
    abilitazione.in_lista = False
    abilitazione.save(update_fields=["in_lista", "updated_at"])
    AbilitazioneMacchinaStorico.objects.create(
        legacy_anagrafica_id=abilitazione.legacy_anagrafica_id, asset_id=abilitazione.asset_id,
        competenza_id=abilitazione.competenza_id, livello="", data_rilevazione=timezone.localdate(),
        fonte=AbilitazioneMacchinaStorico.FONTE_MANUALE, note="Mansionario: tolto dalla lista",
    )


def completezza(mansione: CompetenzaSkm, *, n_competenze: int, n_persone: int) -> list[dict]:
    """Cosa serve perché la mansione funzioni in tutto il portale, voce per voce."""
    ruoli = list(mansione.ruoli.all())
    rischi = list(mansione.mansioni_rischio.all())
    reparto = mansione.reparto_effettivo
    return [
        {"chiave": "ruolo", "ok": bool(ruoli), "titolo": "Ruolo",
         "testo": ", ".join(r.nome for r in ruoli) if ruoli else "Senza ruolo la mansione resta in «Da collegare»."},
        {"chiave": "reparto", "ok": bool(reparto), "titolo": "Reparto",
         "testo": reparto or "Serve al refresh del caporeparto e al reparto principale della persona."},
        {"chiave": "rischio", "ok": bool(rischi), "titolo": "Mansione di rischio",
         "testo": ", ".join(m.nome for m in rischi) if rischi else "Senza, DPI, visite e schede di sicurezza non si ricavano."},
        {"chiave": "competenze", "ok": n_competenze > 0, "titolo": "Competenze",
         "testo": f"{n_competenze} definit{'a' if n_competenze == 1 else 'e'}" if n_competenze
         else "Senza, vale il livello messo a mano: la valutazione non è uniforme."},
        {"chiave": "persone", "ok": n_persone > 0, "titolo": "Persone",
         "testo": f"{n_persone} in lista" if n_persone else "Nessuno è ancora assegnato."},
    ]


def regole_correnti() -> dict:
    """Soglia e regola di calcolo in vigore, con le etichette da mostrare."""
    config = SkillMatrixConfig.get_instance()
    return {
        "soglia": config.soglia_operativa,
        "soglia_label": config.get_soglia_operativa_display(),
        "regola": config.regola_multivoce,
        "regola_label": config.get_regola_multivoce_display(),
        "uomo_solo": config.soglia_uomo_solo,
    }


def nomi_precedenti(mansione: CompetenzaSkm) -> list[str]:
    """Nomi che la mansione ha avuto prima (una riga per nome in ``alias_storici``)."""
    return [r.strip() for r in (mansione.alias_storici or "").splitlines() if r.strip()]


def rinomina(mansione: CompetenzaSkm, nuovo_nome: str, *, salva: bool = True) -> str | None:
    """Cambia il nome visibile della mansione senza rompere i collegamenti.

    Persone, competenze, rischi, ruoli e permessi sono legati alla mansione per
    id e la chiave (``competenza_key``) non cambia: il nome è solo l'etichetta.
    Il vecchio nome resta in ``alias_storici`` così l'import Excel (righe senza
    chiave) e le ricerche lo riconoscono ancora. Ritorna il vecchio nome, o
    ``None`` se il nome non cambia.
    """
    nuovo = " ".join((nuovo_nome or "").split())[:255]
    if not nuovo:
        raise ValueError("Il nome della mansione non può essere vuoto.")
    vecchio = mansione.nome
    if nuovo == vecchio:
        return None
    if (CompetenzaSkm.objects.filter(tipo__in=TIPI_MANSIONE, display__iexact=nuovo)
            .exclude(pk=mansione.pk).exists()):
        raise ValueError(f"Esiste già una mansione «{nuovo}».")
    alias = [a for a in nomi_precedenti(mansione) if a.casefold() != nuovo.casefold()]
    if vecchio and vecchio.casefold() != nuovo.casefold() and vecchio.casefold() not in {a.casefold() for a in alias}:
        alias.append(vecchio)
    mansione.alias_storici = "\n".join(alias)
    mansione.display = nuovo
    if salva:
        mansione.save(update_fields=["display", "alias_storici", "updated_at"])
    return vecchio


def chiave_nuova(nome: str) -> str:
    """Chiave univoca per una mansione nata nel portale (non dal foglio MOD.187)."""
    import re

    base = "MANS-" + re.sub(r"[^0-9A-Z]+", "-", (nome or "").upper()).strip("-")[:100]
    chiave, n = base, 2
    while CompetenzaSkm.objects.filter(competenza_key=chiave).exists():
        chiave, n = f"{base}-{n}", n + 1
    return chiave


@transaction.atomic
def crea_processo(nome: str, *, reparto_id=None, ruoli_ids=()) -> CompetenzaSkm:
    """Mansione nuova di tipo processo (le macchine nascono dalla skill matrix)."""
    from ..models import Reparto, RuoloOperativo

    nome = (nome or "").strip()[:255]
    if not nome:
        raise ValueError("Scrivi il nome della mansione.")
    if CompetenzaSkm.objects.filter(tipo__in=TIPI_MANSIONE, display__iexact=nome).exists():
        raise ValueError(f"Esiste già una mansione «{nome}».")
    mansione = CompetenzaSkm.objects.create(
        competenza_key=chiave_nuova(nome), display=nome, tipo=CompetenzaSkm.TIPO_PROCESSO,
        reparto=Reparto.objects.filter(pk=reparto_id, is_active=True).first() if reparto_id else None,
    )
    mansione.ruoli.set(RuoloOperativo.objects.filter(pk__in=list(ruoli_ids), is_active=True))
    return mansione


@transaction.atomic
def salva_struttura(mansione: CompetenzaSkm, *, area_id=None, processo_id=None, abilitazione=False) -> None:
    """Area (il reparto la segue), processo SGI e abilitazione con validità della mansione."""
    from sistema_gestione.models import Processo

    from ..models import AreaAziendale

    mansione.area = AreaAziendale.objects.filter(pk=area_id).first() if area_id else None
    mansione.processo_sgi = Processo.objects.filter(pk=processo_id).first() if processo_id else None
    mansione.abilitazione_con_scadenza = bool(abilitazione)
    campi = ["area", "processo_sgi", "abilitazione_con_scadenza", "updated_at"]
    if mansione.area is None and mansione.asset_id and mansione.reparto_id:
        # Macchina tolta dall'area: torna a valere il reparto scritto sulla macchina.
        mansione.reparto = None
        campi.append("reparto")
    mansione.save(update_fields=campi)


@transaction.atomic
def salva_editor(mansione: CompetenzaSkm, *, nome: str, ruoli_ids, rischi_ids, reparto_id, attiva: bool,
                 righe: list[dict], struttura: dict | None = None) -> dict:
    """Configurazione e competenze di una mansione in un colpo solo (editor della struttura).

    ``righe``: una per competenza, ``{"id", "nome", "livello_minimo", "bloccante",
    "corso_id", "qualifica_id", "processo_id", "ordine", "togli"}``; ``id`` vuoto =
    competenza nuova (si salta se anche il nome è vuoto). Tutto o niente: al primo
    errore si annulla e si solleva ``ValueError`` con il numero della riga.
    """
    from ..models import VoceMacchinaCatalogo
    from .mansionario_competenze import salva_competenza

    salva_configurazione(mansione, ruoli_ids=ruoli_ids, rischi_ids=rischi_ids, reparto_id=reparto_id,
                         attiva=attiva)
    if struttura is not None:
        salva_struttura(mansione, **struttura)
    conta = {"salvate": 0, "nuove": 0, "tolte": 0, "nome_prima": None}
    if (nome or "").strip():
        conta["nome_prima"] = rinomina(mansione, nome)
    voci = {v.pk: v for v in VoceMacchinaCatalogo.objects.filter(mansione=mansione)}
    for i, r in enumerate(righe, 1):
        voce = voci.get(r.get("id")) if r.get("id") else None
        if r.get("id") and voce is None:
            raise ValueError(f"Riga {i}: la competenza non appartiene a questa mansione.")
        if voce is not None and r.get("togli"):
            if voce.attiva:
                voce.attiva = False
                voce.save(update_fields=["attiva"])
                conta["tolte"] += 1
            continue
        if voce is None and not (r.get("nome") or "").strip():
            continue
        try:
            salva_competenza(
                mansione, voce=voce, nome=r.get("nome"), livello_minimo=(r.get("livello_minimo") or "U").upper(),
                bloccante=bool(r.get("bloccante")), corso_id=r.get("corso_id"), qualifica_id=r.get("qualifica_id"),
                processo_id=r.get("processo_id"), ordine=r.get("ordine") or 0,
            )
        except ValueError as exc:
            raise ValueError(f"Riga {i}: {exc}") from exc
        conta["nuove" if voce is None else "salvate"] += 1
    return conta


def reparto_principale(legacy_anagrafica_id: int) -> str:
    """Reparto della mansione con il livello più alto; a parità, la più vecchia (D13)."""
    abil = list(
        AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=legacy_anagrafica_id, in_lista=True,
                                            competenza__isnull=False)
        .select_related("competenza__asset", "competenza__reparto")
    )
    if not abil:
        return ""
    lontano = timezone.localdate().replace(year=9999)
    abil.sort(key=lambda a: (-ordinale_livello(a.livello), a.data_assegnazione or lontano, a.pk))
    return abil[0].competenza.reparto_effettivo


def da_rivedere_dopo_spostamento(legacy_anagrafica_id: int) -> list[dict]:
    """Mansioni lavorative della persona che non tornano più con reparto e ruoli di oggi.

    Fase 3 del riordino capo/team (16/10/2026): uno spostamento cambia reparto e
    ruolo ma non tocca il Mansionario, e le mansioni di rischio ricavate da
    macchine che la persona non usa più restano attive. Qui si **propone**: è
    chi registra a decidere cosa togliere. Motivi: la mansione è di un altro
    reparto; la mansione è prevista per ruoli che la persona non ricopre più.
    """
    from django.db.models import Q

    from ..models import DipendenteAnagraficaAziendale, DipendenteRuoloOperativo

    oggi = timezone.localdate()
    az = (
        DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=legacy_anagrafica_id)
        .select_related("area_aziendale__reparto").first()
    )
    reparto = ""
    if az is not None:
        if az.area_aziendale_id and az.area_aziendale.reparto_id:
            reparto = az.area_aziendale.reparto.nome
        reparto = (reparto or az.area or "").strip()
    ruoli = set(
        DipendenteRuoloOperativo.objects.filter(
            Q(data_fine__isnull=True) | Q(data_fine__gte=oggi), legacy_anagrafica_id=legacy_anagrafica_id,
        ).values_list("ruolo_id", flat=True)
    )
    out = []
    for ab in (
        AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=legacy_anagrafica_id, in_lista=True,
                                            competenza__isnull=False)
        .select_related("competenza__asset", "competenza__reparto")
        .prefetch_related("competenza__ruoli")
    ):
        mansione = ab.competenza
        motivi = []
        rep_mansione = (mansione.reparto_effettivo or "").strip()
        if reparto and rep_mansione and rep_mansione.casefold() != reparto.casefold():
            motivi.append(f"è del reparto {rep_mansione}")
        ruoli_mansione = {r.pk: r.nome for r in mansione.ruoli.all()}
        if ruoli_mansione and not (set(ruoli_mansione) & ruoli):
            motivi.append("è prevista per " + ", ".join(sorted(ruoli_mansione.values())))
        if motivi:
            out.append({"abilitazione": ab, "mansione": mansione, "nome": str(mansione), "livello": ab.livello,
                        "motivi": motivi})
    out.sort(key=lambda r: r["nome"].casefold())
    return out
