"""Preset dei ruoli del portale: ruoli pronti da attribuire alle persone.

Ogni preset e' un ``AccessGroup`` (codice ``ruolo-<chiave>``) con il suo ordine
(``priority``: fra i ruoli di una persona decide il piu' alto che si esprime) e
le celle della matrice. I preset **concedono soltanto**: un ruolo che non
concede tace e decide il successivo. I «no» espliciti si mettono a mano, come
eccezione, dalla pagina «Ruoli e permessi».

Notazione delle celle: ``{modulo: {azione: ambito}}`` con ambito
«propri» / «team» / «tutti». ``TUTTE`` = le sette azioni standard.

Applicare i preset non sovrascrive le celle gia' modificate a mano: crea i
ruoli mancanti e le celle mancanti. ``reset=True`` riporta un ruolo al preset.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.permessi.registro import AZIONI_STANDARD

P, T, A = "propri", "team", "tutti"
TUTTE = AZIONI_STANDARD


# Dotazione base di ogni preset: login/logout, home e dashboard, profilo,
# preferenze, notifiche, rubrica, organigramma, cambio password (modulo
# «bacheca») e lettura delle notizie. Un ruolo assegnato da solo deve gia'
# far entrare la persona nel portale, senza dipendere dal ruolo base.
_DOTAZIONE_BASE = {"bacheca": {"vedere": P, "creare": P, "modificare": P}, "notizie": {"vedere": A}}


def _celle(**moduli) -> dict[str, dict[str, str]]:
    """Celle di un preset: la dotazione base, poi le sue (che vincono)."""
    celle = {modulo: dict(azioni) for modulo, azioni in _DOTAZIONE_BASE.items()}
    for modulo, azioni in moduli.items():
        celle[modulo] = {**celle.get(modulo, {}), **azioni}
    return celle


def _tutte(ambito: str = A, *, senza: tuple[str, ...] = ()) -> dict[str, str]:
    return {azione: ambito for azione in TUTTE if azione not in senza}


def _ve(ambito: str = A) -> dict[str, str]:
    return {"vedere": ambito, "esportare": ambito}


# Cio' che ogni posizione dell'organigramma ha in piu' rispetto all'Operatore:
# aprire i propri ticket IT e usare l'assistente AI.
_DOTAZIONE_POSIZIONE = {"ticket_it": {"vedere": P, "creare": P}, "assistente_ai": {"vedere": P}}


def _posizione(**moduli) -> dict[str, dict[str, str]]:
    """Celle di una posizione: base e dotazione comune, poi le sue (che vincono)."""
    celle = _celle(**_DOTAZIONE_POSIZIONE)
    for modulo, azioni in moduli.items():
        celle[modulo] = {**celle.get(modulo, {}), **azioni}
    return celle


@dataclass(frozen=True)
class Preset:
    chiave: str
    nome: str
    ordine: int
    descrizione: str
    celle: dict[str, dict[str, str]] = field(default_factory=dict)
    amministratore: bool = False
    vede_tutto: bool = False

    @property
    def codice(self) -> str:
        return f"ruolo-{self.chiave}"


# Modello del 15/10/2026: la posizione nell'organigramma porta il ruolo (Direzione,
# Qualita', IT, Manutenzione, Ingegneria, Amministrazione, Caporeparto, Controllo
# qualita'); gli incarichi (Gestione personale, Gestione formazione, Preposto, RLS,
# Addetto emergenze, Referente 27001, Auditor) sono ruoli in piu' sulla stessa
# persona. L'RSPP e' un utente esterno con ruolo a mano. Le chiavi dei preset gia'
# esistenti restano quelle di prima (es. «hr» e' Gestione personale, «dipendente»
# e' l'Operatore), cosi' i ruoli gia' creati restano collegati.
# Ordine: chi vede di piu' sta piu' in alto; un incarico tace dove non serve.
# «Cancellare» non c'e' sulle registrazioni del sistema di gestione (incidenti,
# SDS, RENTRI, audit, CAPA, timbri, eventi SOC): resta all'Amministratore.
PRESETS: tuple[Preset, ...] = (
    Preset(
        "amministratore", "Amministratore del portale", 1000,
        "Vede e fa tutto, su tutti i moduli presenti e futuri. Gestisce utenti, ruoli e permessi. Solo a mano.",
        amministratore=True,
    ),
    Preset(
        "direzione", "Direzione", 800,
        "Vede ed esporta i dati di tutti i moduli, presenti e futuri. Approva i documenti del riesame.",
        # «bacheca vedere» a «tutti»: una cella esplicita vince su «vede tutto» e non deve restringerlo.
        celle=_celle(bacheca={"vedere": A}, sistema_gestione={"approvare": A}, ticket_it={"creare": P}),
        vede_tutto=True,
    ),
    Preset(
        "sicurezza", "RSPP (esterno)", 700,
        "Responsabile del servizio di prevenzione: segnalazioni, DPI, procedure, SDS, formazione sicurezza, "
        "vigilanza dei preposti. Utente esterno, ruolo a mano con scadenza.",
        celle=_celle(
            rilevazione_incidenti=_tutte(senza=("cancellare",)),
            diario_preposto={"vedere": A, "esportare": A, "gestire": A},
            dpi=_tutte(senza=("cancellare",)),
            procedure=_tutte(senza=("cancellare", "approvare")),
            schede_sicurezza=_tutte(senza=("approvare", "cancellare")),
            formazione=_tutte(senza=("cancellare",)),
            visite_mediche={"vedere": A},
            notizie=_tutte(senza=("approvare",)),
            rentri={"vedere": A},
            checklist_operativa={"vedere": A, "esportare": A, "gestire": A},
            report_conformita=_ve(),
            planimetria={"vedere": A},
            capa={"vedere": A, "creare": A, "modificare": A, "esportare": A},
            sistema_gestione={"vedere": A, "modificare": A, "esportare": A},
            attrezzature={"vedere": A},
            assets={"vedere": A},
        ),
    ),
    Preset(
        "amministrazione", "Amministrazione", 650,
        "Contabilità e contatori, acquisti e fornitori, magazzino DPI, carico SDS, registro rifiuti. "
        "Vede l'elenco del personale, non i dati riservati.",
        celle=_posizione(
            assenze=_ve(),
            anagrafica={"vedere": A},
            notizie=_tutte(senza=("approvare",)),
            report_conformita=_ve(),
            contatori=_ve(),
            fornitori={"vedere": A, "creare": A, "modificare": A, "esportare": A},
            dpi={"vedere": A, "gestire": A, "esportare": A},
            schede_sicurezza={"vedere": A, "creare": A},
            rentri={"vedere": A, "creare": A, "modificare": A, "gestire": A, "esportare": A},
            attrezzature={"vedere": A, "modificare": A},
        ),
    ),
    Preset(
        "qualita", "Qualità", 600,
        "Sistema di gestione, documenti e procedure, audit, non conformità, CAPA, timbri, qualifica fornitori.",
        celle=_posizione(
            specifiche=_tutte(senza=("cancellare",)),
            sistema_gestione=_tutte(senza=("cancellare",)),
            capa=_tutte(senza=("cancellare",)),
            anomalie={"vedere": A, "creare": A, "modificare": A, "gestire": A, "esportare": A},
            timbri={"vedere": A, "creare": A, "modificare": A, "gestire": A, "esportare": A},
            suggestion_corner={"vedere": A, "gestire": A, "esportare": A},
            glossario=_tutte(senza=("approvare",)),
            report_conformita=_ve(),
            procedure=_tutte(senza=("cancellare",)),
            fornitori={"vedere": A, "modificare": A, "approvare": A, "esportare": A},
            attrezzature={"vedere": A},
            kickoff={"vedere": A},
        ),
    ),
    Preset(
        "tecnico-it", "IT", 560,
        "Ticket IT, asset, contatori, Security Center operativo, Wi-Fi ospiti.",
        celle=_posizione(
            ticket_it={"vedere": A, "creare": A, "modificare": A, "gestire": A, "esportare": A},
            assets=_tutte(senza=("approvare",)),
            contatori=_tutte(senza=("approvare",)),
            soc=_tutte(senza=("approvare", "cancellare")),
            portale_ospiti={"vedere": A, "gestire": A},
        ),
    ),
    Preset(
        "tecnico-manutenzione", "Manutenzione", 550,
        "Ticket di manutenzione, asset e piani di manutenzione, planimetria, attrezzature.",
        celle=_posizione(
            ticket_manutenzione={"vedere": A, "modificare": A, "gestire": A, "esportare": A},
            assets=_tutte(senza=("approvare",)),
            planimetria={"vedere": A, "modificare": A},
            attrezzature={"vedere": A, "modificare": A},
            carichi_macchina={"vedere": A},
        ),
    ),
    Preset(
        "ufficio-tecnico", "Ingegneria", 520,
        "KICK-OFF, attrezzature, carichi macchina, specifiche; decide sulle anomalie come capocommessa.",
        celle=_posizione(
            kickoff=_tutte(senza=("approvare",)),
            attrezzature=_tutte(senza=("approvare",)),
            carichi_macchina=_tutte(senza=("approvare",)),
            specifiche={"vedere": A, "creare": A},
            anomalie={"vedere": A, "approvare": A},
            assets={"vedere": A},
            fornitori={"vedere": A},
        ),
    ),
    Preset(
        "controllo-qualita", "Controllo qualità", 480,
        "Apre e istruisce le non conformità di tutti i reparti; consulta specifiche, commesse e timbri.",
        celle=_posizione(
            anomalie={"vedere": A, "creare": A, "modificare": A, "esportare": A},
            timbri={"vedere": A},
            specifiche={"vedere": A},
            kickoff={"vedere": A},
            attrezzature={"vedere": A},
            carichi_macchina={"vedere": A},
            capa={"vedere": A, "creare": A},
            checklist_operativa={"vedere": A, "creare": A},
        ),
    ),
    Preset(
        "hr", "Gestione personale", 460,
        "Incarico: anagrafica completa con dati riservati, gestione assenze, scadenziario visite e referti in custodia.",
        celle=_celle(
            assenze={"vedere": A, "esportare": A, "creare": A, "gestire": A},
            anagrafica={**_tutte(senza=("approvare",)), "dati_riservati": A},
            visite_mediche={**_tutte(senza=("approvare", "cancellare")), "referti": A},
            notizie=_tutte(senza=("approvare",)),
            timbri=_ve(),
            report_conformita=_ve(),
        ),
    ),
    Preset(
        "gestione-formazione", "Gestione formazione", 455,
        "Incarico: piano formativo, corsi ed e-learning, presenze, attestati e scadenze di tutta l'azienda.",
        celle=_celle(
            formazione=_tutte(senza=("cancellare",)),
            anagrafica={"vedere": A},
            procedure={"vedere": A},
            report_conformita=_ve(),
        ),
    ),
    Preset(
        "referente-27001", "Referente 27001", 445,
        "Incarico: dichiarazione di applicabilità, eventi di sicurezza, riesame degli accessi. "
        "Vede utenti e ruoli, non li modifica.",
        celle=_celle(
            soc={"vedere": A, "approvare": A, "gestire": A, "esportare": A},
            sistema_gestione={"vedere": A, "creare": A, "modificare": A, "esportare": A},
            gestione_utenti=_ve(),
            ticket_it=_ve(),
            assets=_ve(),
            contatori={"vedere": A},
            piattaforma={"vedere": A},
            portale_ospiti={"vedere": A},
            automazioni={"vedere": A},
            capa={"vedere": A, "creare": A, "modificare": A},
        ),
    ),
    Preset(
        "auditor", "Auditor interno", 440,
        "Incarico: legge le evidenze di tutti i sistemi e registra i propri rilievi.",
        celle=_celle(
            sistema_gestione={"vedere": A, "esportare": A, "modificare": P},
            capa={"vedere": A, "creare": A},
            report_conformita=_ve(),
            specifiche={"vedere": A},
            procedure={"vedere": A},
            timbri={"vedere": A},
            anomalie={"vedere": A},
            fornitori={"vedere": A},
            formazione={"vedere": A},
            rilevazione_incidenti={"vedere": A},
            dpi={"vedere": A},
            rentri={"vedere": A},
        ),
    ),
    Preset(
        "rls", "RLS", 435,
        "Incarico: consultazione su incidenti, procedure, schede di sicurezza e documenti 45001. Nessun dato sanitario.",
        celle=_celle(
            rilevazione_incidenti=_ve(),
            procedure={"vedere": A},
            schede_sicurezza={"vedere": A},
            sistema_gestione={"vedere": A},
            report_conformita={"vedere": A},
            suggestion_corner={"vedere": A},
            planimetria={"vedere": A},
        ),
    ),
    Preset(
        "addetto-emergenze", "Addetto emergenze", 420,
        "Incarico: planimetria con presidi e vie di fuga, controlli periodici dei presidi.",
        celle=_celle(
            planimetria={"vedere": A},
            checklist_operativa={"vedere": P, "creare": P, "modificare": P},
            procedure={"vedere": A},
        ),
    ),
    Preset(
        "responsabile", "Caporeparto", 400,
        "Vede i dati del suo team d'organigramma, approva assenze e DPI del team.",
        celle=_posizione(
            assenze={"vedere": T, "approvare": T, "esportare": T},
            diario_preposto={"vedere": T, "esportare": T},
            rilevazione_incidenti={"vedere": T, "creare": T},
            ticket_manutenzione={"vedere": T, "creare": T},
            kickoff={"vedere": T, "creare": T, "modificare": T},
            anagrafica={"vedere": T},
            visite_mediche={"vedere": T},
            formazione={"vedere": T},
            procedure={"vedere": T},
            checklist_operativa={"vedere": T, "creare": T, "modificare": T},
            capa={"vedere": T, "modificare": T},
            dpi={"vedere": T, "approvare": T},
        ),
    ),
    Preset(
        "preposto", "Preposto", 300,
        "Incarico: diario preposto, segnalazioni e DPI della squadra; verifica formazione, idoneità e procedure del team.",
        celle=_celle(
            assenze={"vedere": T},
            diario_preposto={"vedere": P, "creare": P, "modificare": P, "esportare": P},
            rilevazione_incidenti={"vedere": T, "creare": T},
            ticket_manutenzione={"vedere": T, "creare": T},
            dpi={"vedere": T, "approvare": T},
            schede_sicurezza={"vedere": T},
            checklist_operativa={"vedere": T, "creare": T, "modificare": T},
            kickoff={"vedere": P},
            procedure={"vedere": T},
            formazione={"vedere": T},
            visite_mediche={"vedere": T},
        ),
    ),
    Preset(
        "dipendente", "Operatore", 100,
        "Ruolo base di chiunque abbia un account: proprie assenze, notizie, schede di sicurezza; "
        "segnala incidenti, anomalie e guasti, chiede DPI, prende visione delle procedure.",
        celle=_celle(
            assenze={"vedere": P, "creare": P, "modificare": P},
            schede_sicurezza={"vedere": P},
            rilevazione_incidenti={"vedere": P, "creare": P},
            dpi={"vedere": P, "creare": P},
            procedure={"vedere": P},
            anomalie={"creare": P},
            ticket_manutenzione={"vedere": P, "creare": P},
        ),
    ),
)

# Preset non piu' proposti: i ruoli gia' creati restano, ma non vengono ricreati.
# «magazzino» e' confluito in Amministrazione.
PRESET_RITIRATI = ("magazzino",)

PRESETS_PER_CHIAVE = {p.chiave: p for p in PRESETS}

# Nome e ordine dei preset prima del modello del 15/10: un ruolo che li ha ancora
# (non rinominato ne' riordinato a mano) prende quelli nuovi.
_PRIMA_DEL_MODELLO_ORGANIGRAMMA = {
    "sicurezza": ("Sicurezza (RSPP / HSE)", 700),
    "hr": ("Ufficio Personale (HR)", 650),
    "tecnico-it": ("Tecnico IT", 560),
    "tecnico-manutenzione": ("Tecnico Manutenzione", 550),
    "ufficio-tecnico": ("Ufficio Tecnico / Commerciale", 520),
    "amministrazione": ("Amministrazione / Contabilità", 500),
    "responsabile": ("Responsabile (capo reparto / area)", 400),
    "preposto": ("Preposto (capocantiere / capo squadra)", 300),
    "dipendente": ("Dipendente", 100),
}


def riallinea_preset_modello(gruppi=None, celle=None) -> dict:
    """Porta i ruoli nati dai preset al modello attuale, senza toccare il lavoro a mano.

    - nome, descrizione e ordine cambiano solo se sono ancora quelli del preset precedente;
    - le celle con nota «preset …» si allineano (aggiunte, cambiate, tolte);
    - le celle «modificata a mano» restano come sono;
    - i preset nuovi si creano.

    ``gruppi``/``celle`` sono i model (anche storici, da una migrazione).
    """
    if gruppi is None or celle is None:
        from core.models import AccessGroup, RuoloPermessoModulo

        gruppi, celle = AccessGroup, RuoloPermessoModulo
    esito = {"creati": 0, "rinominati": 0, "celle_aggiunte": 0, "celle_cambiate": 0, "celle_tolte": 0}
    for preset in PRESETS:
        ruolo = gruppi.objects.filter(code=preset.codice).first()
        if ruolo is None:
            ruolo = gruppi.objects.create(
                code=preset.codice, label=preset.nome, description=preset.descrizione[:500],
                priority=preset.ordine, amministratore=preset.amministratore,
                vede_tutto=preset.vede_tutto, preset=preset.chiave,
            )
            esito["creati"] += 1
        else:
            prima = _PRIMA_DEL_MODELLO_ORGANIGRAMMA.get(preset.chiave)
            campi = []
            if prima and ruolo.label == prima[0] and ruolo.label != preset.nome:
                ruolo.label = preset.nome
                ruolo.description = preset.descrizione[:500]
                campi += ["label", "description"]
            if prima and ruolo.priority == prima[1] and ruolo.priority != preset.ordine:
                ruolo.priority = preset.ordine
                campi.append("priority")
            if campi:
                ruolo.save(update_fields=campi)
                esito["rinominati"] += 1
        voluti = {(m, a): amb for m, azioni in preset.celle.items() for a, amb in azioni.items()}
        esistenti = {(c.modulo, c.azione): c for c in celle.objects.filter(ruolo_id=ruolo.id)}
        nota = f"preset {preset.chiave}"
        for chiave, cella in esistenti.items():
            if not str(cella.note or "").startswith("preset "):
                continue  # modificata a mano: decide chi l'ha cambiata
            if chiave not in voluti:
                cella.delete()
                esito["celle_tolte"] += 1
            elif cella.ambito != voluti[chiave] or not cella.consentito:
                cella.ambito, cella.consentito, cella.note = voluti[chiave], True, nota
                cella.save()
                esito["celle_cambiate"] += 1
        for (modulo, azione), ambito in voluti.items():
            if (modulo, azione) not in esistenti:
                celle.objects.create(
                    ruolo_id=ruolo.id, modulo=modulo, azione=azione, ambito=ambito, consentito=True, note=nota
                )
                esito["celle_aggiunte"] += 1
    # Preset ritirati: il ruolo si spegne solo se nessuno lo ha (a mano o dall'organigramma).
    esito["disattivati"] = 0
    for chiave in PRESET_RITIRATI:
        for ruolo in gruppi.objects.filter(preset=chiave, is_active=True):
            if not ruolo.memberships.exists() and not ruolo.ruoli_organigramma.exists():
                ruolo.is_active = False
                ruolo.save(update_fields=["is_active"])
                esito["disattivati"] += 1
    return esito


def applica_preset(*, chiavi=None, reset: bool = False, request=None) -> list[dict]:
    """Crea/aggiorna i ruoli dei preset. Senza ``reset`` non tocca le celle esistenti."""
    from django.db import transaction

    from core.models import AccessGroup, RuoloPermessoModulo
    from core.permessi.registro import modulo as modulo_registrato

    esiti = []
    selezionati = [p for p in PRESETS if not chiavi or p.chiave in set(chiavi)]
    with transaction.atomic():
        for preset in selezionati:
            ruolo, creato = AccessGroup.objects.get_or_create(
                code=preset.codice,
                defaults={
                    "label": preset.nome,
                    "description": preset.descrizione[:500],
                    "priority": preset.ordine,
                    "amministratore": preset.amministratore,
                    "vede_tutto": preset.vede_tutto,
                    "preset": preset.chiave,
                },
            )
            if reset and not creato:
                ruolo.label = preset.nome
                ruolo.description = preset.descrizione[:500]
                ruolo.priority = preset.ordine
                ruolo.amministratore = preset.amministratore
                ruolo.vede_tutto = preset.vede_tutto
                ruolo.preset = preset.chiave
                ruolo.save()
                RuoloPermessoModulo.objects.filter(ruolo=ruolo).delete()
            elif not ruolo.preset:
                ruolo.preset = preset.chiave
                ruolo.save(update_fields=["preset", "updated_at"])

            create = 0
            for chiave_modulo, azioni in preset.celle.items():
                if modulo_registrato(chiave_modulo) is None:
                    raise ValueError(f"Preset «{preset.chiave}»: modulo «{chiave_modulo}» non registrato.")
                for azione, ambito in azioni.items():
                    _cella, nuova = RuoloPermessoModulo.objects.get_or_create(
                        ruolo=ruolo,
                        modulo=chiave_modulo,
                        azione=azione,
                        defaults={"ambito": ambito, "consentito": True, "note": f"preset {preset.chiave}"},
                    )
                    create += int(nuova)
            esiti.append({"ruolo": ruolo, "creato": creato, "celle_create": create})

    if request is not None:
        from core.audit import log_action

        log_action(
            request,
            "permessi_preset_applicati",
            "permessi",
            {"preset": [p.chiave for p in selezionati], "reset": reset},
        )
    from core.permessi.cache import invalida_permessi

    invalida_permessi()
    return esiti
