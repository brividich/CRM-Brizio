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


def _celle(**moduli) -> dict[str, dict[str, str]]:
    return {modulo: dict(azioni) for modulo, azioni in moduli.items()}


def _tutte(ambito: str = A, *, senza: tuple[str, ...] = ()) -> dict[str, str]:
    return {azione: ambito for azione in TUTTE if azione not in senza}


def _ve(ambito: str = A) -> dict[str, str]:
    return {"vedere": ambito, "esportare": ambito}


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


PRESETS: tuple[Preset, ...] = (
    Preset(
        "amministratore", "Amministratore del portale", 1000,
        "Vede e fa tutto, su tutti i moduli presenti e futuri. Gestisce utenti, ruoli e permessi.",
        amministratore=True,
    ),
    Preset(
        "direzione", "Direzione", 800,
        "Vede ed esporta i dati di tutti i moduli, presenti e futuri. Non modifica nulla.",
        vede_tutto=True,
    ),
    Preset(
        "sicurezza", "Sicurezza (RSPP / HSE)", 700,
        "Gestisce segnalazioni, DPI, procedure, schede di sicurezza e formazione di tutta l'azienda.",
        celle=_celle(
            rilevazione_incidenti=_tutte(),
            diario_preposto={"vedere": A, "esportare": A, "gestire": A},
            dpi=_tutte(senza=("cancellare",)),
            procedure=_tutte(senza=("cancellare", "approvare")),
            schede_sicurezza=_tutte(senza=("approvare",)),
            formazione=_tutte(senza=("cancellare",)),
            visite_mediche={"vedere": A},
            notizie=_tutte(senza=("approvare",)),
            rentri=_tutte(senza=("approvare",)),
            checklist_operativa={"vedere": A, "esportare": A, "gestire": A},
            report_conformita=_ve(),
            planimetria={"vedere": A},
        ),
    ),
    Preset(
        "hr", "Ufficio Personale (HR)", 650,
        "Anagrafica, visite e formazione di tutti; vede ed esporta tutte le assenze.",
        celle=_celle(
            assenze={"vedere": A, "esportare": A, "creare": A, "gestire": A},
            anagrafica=_tutte(senza=("approvare",)),
            visite_mediche=_tutte(senza=("approvare",)),
            formazione=_tutte(senza=("cancellare",)),
            notizie=_tutte(senza=("approvare",)),
            timbri=_tutte(senza=("approvare",)),
            report_conformita=_ve(),
        ),
    ),
    Preset(
        "qualita", "Qualità", 600,
        "Sistema di gestione, specifiche, CAPA, anomalie, timbri e suggerimenti.",
        celle=_celle(
            specifiche=_tutte(),
            sistema_gestione=_tutte(),
            capa=_tutte(),
            anomalie={"vedere": A, "modificare": A, "gestire": A, "esportare": A},
            timbri=_tutte(senza=("approvare",)),
            suggestion_corner={"vedere": A, "gestire": A, "esportare": A},
            glossario=_tutte(senza=("approvare",)),
            report_conformita=_ve(),
            procedure=_tutte(senza=("cancellare", "approvare")),
            fornitori={"vedere": A, "modificare": A},
        ),
    ),
    Preset(
        "tecnico-it", "Tecnico IT", 560,
        "Vede, assegna e chiude tutti i ticket IT; asset, contatori e Security Center.",
        celle=_celle(
            ticket_it={"vedere": A, "modificare": A, "gestire": A, "esportare": A},
            assets=_tutte(senza=("approvare",)),
            contatori=_tutte(senza=("approvare",)),
            soc=_tutte(senza=("approvare",)),
            portale_ospiti={"vedere": A, "gestire": A},
        ),
    ),
    Preset(
        "tecnico-manutenzione", "Tecnico Manutenzione", 550,
        "Vede, assegna e chiude tutti i ticket di manutenzione; asset e manutenzioni.",
        celle=_celle(
            ticket_manutenzione={"vedere": A, "modificare": A, "gestire": A, "esportare": A},
            assets=_tutte(senza=("approvare",)),
            planimetria={"vedere": A, "modificare": A},
        ),
    ),
    Preset(
        "ufficio-tecnico", "Ufficio Tecnico / Commerciale", 520,
        "KICK-OFF, attrezzature, carichi macchina, specifiche; decide sulle anomalie come capocommessa.",
        celle=_celle(
            kickoff=_tutte(senza=("approvare",)),
            attrezzature=_tutte(senza=("approvare",)),
            carichi_macchina=_tutte(senza=("approvare",)),
            specifiche={"vedere": A, "creare": A},
            anomalie={"vedere": A, "approvare": A},
            assets={"vedere": A},
        ),
    ),
    Preset(
        "magazzino", "Magazzino / Acquisti", 510,
        "Consegne e magazzino DPI, fornitori, schede di sicurezza, registro rifiuti.",
        celle=_celle(
            dpi={"vedere": A, "gestire": A, "esportare": A},
            fornitori={"vedere": A, "creare": A, "modificare": A, "esportare": A},
            schede_sicurezza={"vedere": A, "creare": A},
            rentri={"vedere": A, "creare": A},
            attrezzature={"vedere": A, "modificare": A},
        ),
    ),
    Preset(
        "amministrazione", "Amministrazione / Contabilità", 500,
        "Fatture e contatori, fornitori, dati contrattuali in anagrafica.",
        celle=_celle(
            contatori=_ve(),
            fornitori=_ve(),
            anagrafica={"vedere": A},
        ),
    ),
    Preset(
        "responsabile", "Responsabile (capo reparto / area)", 400,
        "Vede i dati del suo team d'organigramma e approva le assenze del team.",
        celle=_celle(
            assenze={"vedere": T, "approvare": T, "esportare": T},
            diario_preposto={"vedere": T, "esportare": T},
            rilevazione_incidenti={"vedere": T},
            ticket_manutenzione={"vedere": T, "creare": T},
            kickoff={"vedere": T, "creare": T, "modificare": T},
            anagrafica={"vedere": T},
            visite_mediche={"vedere": T},
            formazione={"vedere": T},
            procedure={"vedere": T},
            checklist_operativa={"vedere": T, "creare": T, "modificare": T},
            capa={"vedere": T, "modificare": T},
            dpi={"vedere": T},
        ),
    ),
    Preset(
        "preposto", "Preposto (capocantiere / capo squadra)", 300,
        "Tiene il diario preposto, segnala per la squadra, vede assenze e ticket del team.",
        celle=_celle(
            assenze={"vedere": T},
            diario_preposto={"vedere": P, "creare": P, "modificare": P, "esportare": P},
            rilevazione_incidenti={"vedere": T, "creare": T},
            ticket_manutenzione={"vedere": T, "creare": T},
            dpi={"vedere": T, "approvare": T},
            schede_sicurezza={"vedere": T},
            checklist_operativa={"vedere": T, "creare": T, "modificare": T},
            kickoff={"vedere": P},
        ),
    ),
    Preset(
        "dipendente", "Dipendente", 100,
        "Ruolo base di chiunque abbia un account: vede e crea solo i propri dati.",
        celle=_celle(
            bacheca={"vedere": P, "creare": P, "modificare": P},
            assistente_ai={"vedere": P},
            assenze={"vedere": P, "creare": P, "modificare": P},
            rilevazione_incidenti={"vedere": P, "creare": P},
            ticket_it={"vedere": P, "creare": P},
            ticket_manutenzione={"vedere": P, "creare": P},
            dpi={"vedere": P, "creare": P},
            notizie={"vedere": A},
            procedure={"vedere": P},
            schede_sicurezza={"vedere": P},
            formazione={"vedere": P},
            suggestion_corner={"vedere": P, "creare": P},
            glossario={"vedere": A},
            sistema_gestione={"vedere": P},
            anomalie={"creare": P},
        ),
    ),
)

PRESETS_PER_CHIAVE = {p.chiave: p for p in PRESETS}


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
