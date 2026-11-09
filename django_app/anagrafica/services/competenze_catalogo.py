"""Catalogo unico delle competenze (Struttura Fase 5).

La stessa competenza («Lettura del disegno», «Set-up macchina»…) compare in più
mansioni: ogni mansione tiene la sua voce con minimo e requisiti, il catalogo le
lega per nome. Da qui:

- una competenza si rinomina una volta e vale per tutte le mansioni;
- due voci scritte in modo diverso si uniscono;
- il livello già valutato su una mansione si propone sulle altre (``livelli_noti``);
- la matrice persone × competenze dice chi sa fare cosa, al di là della mansione.
"""
from __future__ import annotations

import re

from django.db import transaction

from ..models import (
    AbilitazioneMacchina, AbilitazioneMacchinaVoce, CompetenzaCatalogo, CompetenzaSkm, ValutazioneCompetenzaStorico,
    VoceMacchinaCatalogo, ordinale_livello,
)


def chiave(nome: str) -> str:
    return re.sub(r"\s+", " ", (nome or "").strip()).casefold()[:160]


def collega(voce: VoceMacchinaCatalogo) -> CompetenzaCatalogo | None:
    """Lega la voce al catalogo per nome (crea la competenza se manca)."""
    k = chiave(voce.nome)
    if not k:
        return None
    cat = CompetenzaCatalogo.objects.filter(chiave=k).first()
    if cat is None:
        cat = CompetenzaCatalogo.objects.create(nome=" ".join(voce.nome.split())[:150], chiave=k)
    elif not cat.attiva:
        cat.attiva = True
        cat.save(update_fields=["attiva", "updated_at"])
    if voce.catalogo_id != cat.pk:
        voce.catalogo = cat
        voce.save(update_fields=["catalogo"])
    return cat


def elenco() -> list[dict]:
    """Competenze del catalogo usate da almeno una mansione attiva, con mansioni e persone valutate."""
    voci = list(VoceMacchinaCatalogo.objects.filter(catalogo__isnull=False, attiva=True, mansione__isnull=False)
                .select_related("mansione", "catalogo", "corso").order_by("mansione__display"))
    valutate: dict[int, set[int]] = {}
    for cat_id, lid in (AbilitazioneMacchinaVoce.objects.filter(voce__catalogo__isnull=False)
                        .values_list("voce__catalogo_id", "abilitazione__legacy_anagrafica_id")):
        valutate.setdefault(cat_id, set()).add(lid)
    righe: dict[int, dict] = {}
    for v in voci:
        r = righe.setdefault(v.catalogo_id, {"catalogo": v.catalogo, "mansioni": [], "requisiti": set(), "corsi": []})
        r["mansioni"].append(v.mansione)
        if v.corso_id and v.corso not in r["corsi"]:
            r["corsi"].append(v.corso)
        if v.corso_id or v.qualifica_id or v.processo_mpq_id:
            r["requisiti"].add(v.mansione_id)
    out = []
    for cat_id, r in righe.items():
        r["n_persone"] = len(valutate.get(cat_id, ()))
        r["n_requisiti"] = len(r.pop("requisiti"))
        out.append(r)
    out.sort(key=lambda r: (-len(r["mansioni"]), r["catalogo"].nome.casefold()))
    return out


@transaction.atomic
def rinomina(cat: CompetenzaCatalogo, nuovo_nome: str) -> int:
    """Nuovo nome per la competenza e per tutte le sue voci. Ritorna quante voci ha toccato."""
    nuovo = " ".join((nuovo_nome or "").split())[:150]
    if not nuovo:
        raise ValueError("Il nome è obbligatorio.")
    k = chiave(nuovo)
    altra = CompetenzaCatalogo.objects.filter(chiave=k).exclude(pk=cat.pk).first()
    if altra is not None:
        raise ValueError(f"Esiste già la competenza «{altra.nome}»: usa «Unisci» invece di rinominare.")
    cat.nome, cat.chiave = nuovo, k
    cat.save(update_fields=["nome", "chiave", "updated_at"])
    return VoceMacchinaCatalogo.objects.filter(catalogo=cat).update(nome=nuovo)


@transaction.atomic
def unisci(da: CompetenzaCatalogo, in_: CompetenzaCatalogo) -> int:
    """Le voci di ``da`` passano a ``in_`` (col suo nome); ``da`` si spegne.

    Una mansione che ha già entrambe le competenze attive non si unisce: i livelli
    registrati sulle due voci andrebbero scelti a mano.
    """
    if da.pk == in_.pk:
        raise ValueError("Una competenza non si unisce a sé stessa.")
    doppie = (set(VoceMacchinaCatalogo.objects.filter(catalogo=da, attiva=True).values_list("mansione_id", flat=True))
              & set(VoceMacchinaCatalogo.objects.filter(catalogo=in_, attiva=True).values_list("mansione_id", flat=True)))
    doppie.discard(None)
    if doppie:
        nomi = ", ".join(CompetenzaSkm.objects.filter(pk__in=doppie).order_by("display").values_list("display", flat=True))
        raise ValueError(f"Queste mansioni hanno già entrambe le competenze: {nomi}. Togline una dalla mansione, poi unisci.")
    n = VoceMacchinaCatalogo.objects.filter(catalogo=da).update(catalogo=in_, nome=in_.nome)
    ValutazioneCompetenzaStorico.objects.filter(catalogo=da).update(catalogo=in_)
    da.attiva = False
    da.save(update_fields=["attiva", "updated_at"])
    return n


def livelli_noti(legacy_id: int, *, escludi_abilitazione_id=None) -> dict[int, dict]:
    """{catalogo id: {livello, mansione}}: il livello più alto già valutato altrove dalla persona."""
    out: dict[int, dict] = {}
    qs = (AbilitazioneMacchinaVoce.objects
          .filter(abilitazione__legacy_anagrafica_id=legacy_id, voce__catalogo__isnull=False)
          .select_related("voce", "abilitazione__competenza"))
    if escludi_abilitazione_id:
        qs = qs.exclude(abilitazione_id=escludi_abilitazione_id)
    for r in qs:
        attuale = out.get(r.voce.catalogo_id)
        if attuale is None or ordinale_livello(r.livello) > ordinale_livello(attuale["livello"]):
            out[r.voce.catalogo_id] = {"livello": r.livello, "mansione": r.abilitazione.competenza}
    return out


def registra_storico(abilitazione: AbilitazioneMacchina, voce: VoceMacchinaCatalogo, prima: str, dopo: str,
                     *, user=None) -> None:
    if (prima or "") == (dopo or ""):
        return
    nome = ""
    if user is not None and getattr(user, "pk", None):
        nome = (user.get_full_name() or user.get_username())[:200]
    ValutazioneCompetenzaStorico.objects.create(
        legacy_anagrafica_id=abilitazione.legacy_anagrafica_id, voce=voce, catalogo_id=voce.catalogo_id,
        mansione_id=abilitazione.competenza_id, competenza_nome=voce.nome[:150],
        livello_prima=prima or "", livello=dopo or "", valutato_da=nome,
    )


def storico_persona(legacy_id: int, limit: int = 40) -> list[ValutazioneCompetenzaStorico]:
    return list(ValutazioneCompetenzaStorico.objects.filter(legacy_anagrafica_id=legacy_id)
                .select_related("mansione")[:limit])


def matrice(reparto_id: int | None = None) -> dict:
    """Persone in lista (sul reparto, se dato) × competenze del catalogo: il livello più alto per persona."""
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    abil = AbilitazioneMacchina.objects.filter(in_lista=True, competenza__isnull=False, competenza__attiva=True)
    if reparto_id:
        from django.db.models import Q

        abil = abil.filter(Q(competenza__area__reparto_id=reparto_id)
                           | Q(competenza__area__isnull=True, competenza__reparto_id=reparto_id))
    abil_ids = list(abil.values_list("pk", flat=True))
    celle: dict[tuple[int, int], str] = {}
    colonne: dict[int, CompetenzaCatalogo] = {}
    for r in (AbilitazioneMacchinaVoce.objects.filter(abilitazione_id__in=abil_ids, voce__catalogo__isnull=False,
                                                      voce__attiva=True)
              .select_related("voce__catalogo", "abilitazione")):
        k = (r.abilitazione.legacy_anagrafica_id, r.voce.catalogo_id)
        colonne[r.voce.catalogo_id] = r.voce.catalogo
        if ordinale_livello(r.livello) > ordinale_livello(celle.get(k)):
            celle[k] = r.livello
    # Anche le competenze richieste ma mai valutate: colonna vuota, si vede il buco.
    for v in (VoceMacchinaCatalogo.objects.filter(mansione__abilitazioni__pk__in=abil_ids, attiva=True,
                                                  catalogo__isnull=False).select_related("catalogo").distinct()):
        colonne.setdefault(v.catalogo_id, v.catalogo)
    persone_ids = sorted(set(abil.values_list("legacy_anagrafica_id", flat=True)))
    nomi = {int(r["id"]): naming.nome_completo(r.get("nome"), r.get("cognome"))
            for r in fetch_anagrafica_rows(ids=persone_ids)} if persone_ids else {}
    cols = sorted(colonne.values(), key=lambda c: c.nome.casefold())
    righe = [{"legacy_id": pid, "nome": nomi.get(pid, f"#{pid}"),
              "livelli": [celle.get((pid, c.pk), "") for c in cols]} for pid in persone_ids]
    righe.sort(key=lambda r: r["nome"].casefold())
    return {"colonne": cols, "righe": righe}


# ---------------------------------------------------------------------------
# Scheda della singola competenza: ruoli → mansioni → persone → requisiti
# ---------------------------------------------------------------------------
STATO_OK = "ok"
STATO_SOTTO = "sotto"
STATO_REQUISITO = "requisito"
STATO_DA_VALUTARE = "da_valutare"
STATI_SCHEDA = {
    STATO_REQUISITO: "Manca il requisito",
    STATO_DA_VALUTARE: "Da valutare",
    STATO_SOTTO: "Sotto il minimo",
    STATO_OK: "La sa fare",
}


def scheda(cat: CompetenzaCatalogo) -> dict:
    """Tutto quello che riguarda una competenza, visto da lei.

    Il livello di ogni persona su ogni mansione si calcola con la stessa funzione
    della scheda della mansione (``mansionario_competenze.valuta``): stessi numeri,
    compreso il tetto «I» quando manca il requisito formale.
    """
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    from . import mansionario_competenze as comp_svc
    from .mansionario_struttura import TIPI_MANSIONE

    voci = list(VoceMacchinaCatalogo.objects.filter(
        catalogo=cat, attiva=True, mansione__isnull=False, mansione__attiva=True, mansione__tipo__in=TIPI_MANSIONE,
    ).select_related("mansione", "corso", "qualifica", "processo_mpq").prefetch_related("mansione__ruoli")
        .order_by("mansione__display"))
    voce_di = {v.mansione_id: v for v in voci}
    abil = list(AbilitazioneMacchina.objects.filter(competenza_id__in=list(voce_di), in_lista=True)
                .prefetch_related("voci"))
    ids = sorted({a.legacy_anagrafica_id for a in abil})
    anag = {int(r["id"]): r for r in fetch_anagrafica_rows(ids=ids)} if ids else {}
    requisiti = comp_svc.Requisiti(ids, voci)

    # Ruoli: quelli delle mansioni che chiedono la competenza (il filo a ritroso).
    ruoli: dict[int, dict] = {}
    for v in voci:
        for r in v.mansione.ruoli.all():
            ruoli.setdefault(r.pk, {"ruolo": r, "mansioni": []})["mansioni"].append(v.mansione)

    persone: dict[int, dict] = {}
    per_mansione = {v.mansione_id: {"voce": v, "mansione": v.mansione, "in_lista": 0, "ok": 0} for v in voci}
    for a in abil:
        v = voce_di[a.competenza_id]
        riga = comp_svc.valuta(a, voci=[v], requisiti=requisiti).voci[0]
        salvato = next((x.livello for x in a.voci.all() if x.voce_id == v.pk), "")
        sospesa = a.stato == AbilitazioneMacchina.STATO_SOSPESA
        if riga["requisito"]:
            stato = STATO_REQUISITO
        elif not salvato:
            stato = STATO_DA_VALUTARE
        elif riga["sotto"]:
            stato = STATO_SOTTO
        else:
            stato = STATO_OK
        r = anag.get(a.legacy_anagrafica_id, {})
        p = persone.setdefault(a.legacy_anagrafica_id, {
            "legacy_id": a.legacy_anagrafica_id,
            "nome": naming.nome_completo(r.get("nome"), r.get("cognome")) or f"#{a.legacy_anagrafica_id}",
            "reparto": (r.get("reparto") or "").strip(),
            "mansioni": [], "livello": "", "requisiti": [],
        })
        p["mansioni"].append({"mansione": v.mansione, "livello": riga["livello"], "minimo": v.livello_minimo,
                              "stato": stato, "requisito": riga["requisito"], "sospesa": sospesa})
        if ordinale_livello(riga["livello"]) > ordinale_livello(p["livello"]):
            p["livello"] = riga["livello"]
        if riga["requisito"] and riga["requisito"] not in p["requisiti"]:
            p["requisiti"].append(riga["requisito"])
        if not sospesa:
            per_mansione[v.mansione_id]["in_lista"] += 1
            per_mansione[v.mansione_id]["ok"] += stato == STATO_OK

    # Una persona, uno stato: il problema più urgente fra le sue mansioni attive.
    priorita = [STATO_REQUISITO, STATO_DA_VALUTARE, STATO_SOTTO, STATO_OK]
    for p in persone.values():
        attive = [m for m in p["mansioni"] if not m["sospesa"]] or p["mansioni"]
        p["stato"] = min((m["stato"] for m in attive), key=priorita.index)
        p["stato_label"] = STATI_SCHEDA[p["stato"]]
        p["sospesa"] = all(m["sospesa"] for m in p["mansioni"])
        # Dove intervenire: la prima mansione con quel problema.
        p["mansione_da_fare"] = next((m["mansione"] for m in attive if m["stato"] == p["stato"]), None)
    elenco = sorted(persone.values(), key=lambda p: (p["sospesa"], priorita.index(p["stato"]), p["nome"].casefold()))
    conta = {s: sum(1 for p in elenco if p["stato"] == s and not p["sospesa"]) for s in priorita}

    # Requisiti formali: chi è in lista senza il corso, la qualifica o il MOD.128 valido.
    corsi: dict[int, dict] = {}
    altri: dict[tuple, dict] = {}
    for v in voci:
        in_lista = [a.legacy_anagrafica_id for a in abil
                    if a.competenza_id == v.mansione_id and a.stato != AbilitazioneMacchina.STATO_SOSPESA]
        if v.corso_id:
            c = corsi.setdefault(v.corso_id, {"corso": v.corso, "mansioni": [], "mancanti": set()})
            c["mansioni"].append(v.mansione)
            c["mancanti"] |= {lid for lid in in_lista if (lid, v.corso_id) not in requisiti.corsi_ok}
        for tipo, obj in (("qualifica", v.qualifica), ("MOD.128", v.processo_mpq)):
            if obj is None:
                continue
            q = altri.setdefault((tipo, obj.pk), {"tipo": tipo, "oggetto": obj, "mansioni": [], "mancanti": set()})
            q["mansioni"].append(v.mansione)
            vista = VoceMacchinaCatalogo(qualifica=v.qualifica if tipo == "qualifica" else None,
                                         processo_mpq=v.processo_mpq if tipo == "MOD.128" else None)
            q["mancanti"] |= {lid for lid in in_lista if requisiti.mancante(vista, lid)}

    def _nomi(ids_):
        return sorted(({"legacy_id": i, "nome": persone[i]["nome"]} for i in ids_ if i in persone),
                      key=lambda x: x["nome"].casefold())

    req_corsi = [{**c, "mancanti": _nomi(c["mancanti"])} for c in corsi.values()]
    req_altri = [{**q, "mancanti": _nomi(q["mancanti"])} for q in altri.values()]

    storico = list(ValutazioneCompetenzaStorico.objects.filter(catalogo=cat)
                   .select_related("mansione").order_by("-valutato_il", "-pk")[:25])
    ids_storico = {s.legacy_anagrafica_id for s in storico} - set(anag)
    if ids_storico:
        anag.update({int(r["id"]): r for r in fetch_anagrafica_rows(ids=sorted(ids_storico))})
    for s in storico:
        r = anag.get(s.legacy_anagrafica_id, {})
        s.persona_nome = naming.nome_completo(r.get("nome"), r.get("cognome")) or f"#{s.legacy_anagrafica_id}"

    return {
        "voci": voci,
        "ruoli": sorted(ruoli.values(), key=lambda r: r["ruolo"].nome.casefold()),
        "mansioni": list(per_mansione.values()),
        "persone": elenco,
        "conta": conta,
        "req_corsi": req_corsi,
        "req_altri": req_altri,
        "n_requisiti_mancanti": sum(len(c["mancanti"]) for c in req_corsi) + sum(len(q["mancanti"]) for q in req_altri),
        "storico": storico,
    }
