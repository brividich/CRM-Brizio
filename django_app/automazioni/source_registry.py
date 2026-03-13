from __future__ import annotations

from copy import deepcopy


AUTOMAZIONI_MODULE_CODE = "automazioni"
AUTOMAZIONI_ACL_ACTIONS = (
    "automazioni_view",
    "automazioni_manage",
    "automazioni_logs",
    "automazioni_execute",
)


def _field(
    *,
    name: str,
    label: str,
    data_type: str,
    description: str,
    db_column: str | None = None,
    is_virtual: bool = False,
    aliases: list[str] | tuple[str, ...] | None = None,
    filterable: bool = True,
    usable_in_trigger: bool = True,
    usable_in_condition: bool = True,
    usable_in_template: bool = True,
    usable_in_action_mapping: bool = True,
    visible_in_admin: bool = True,
) -> dict[str, object]:
    return {
        "name": name,
        "label": label,
        "data_type": data_type,
        "filterable": filterable,
        "usable_in_trigger": usable_in_trigger,
        "usable_in_condition": usable_in_condition,
        "usable_in_template": usable_in_template,
        "usable_in_action_mapping": usable_in_action_mapping,
        "visible_in_admin": visible_in_admin,
        "description": description,
        "db_column": None if is_virtual else (db_column or name),
        "is_virtual": is_virtual,
        "aliases": list(aliases or []),
    }


_SOURCE_REGISTRY: dict[str, dict[str, object]] = {
    "assenze": {
        "code": "assenze",
        "label": "Assenze",
        "source_app": "assenze",
        "table_name": "assenze",
        "pk_field": "id",
        "supported_operations": ["insert", "update"],
        "description": (
            "Richieste assenza legacy su SQL Server. "
            "Il concetto logico di utente e' mappato sul campo reale `dipendente_id`."
        ),
        "fields": [
            _field(name="id", label="ID", data_type="int", description="Chiave primaria record assenza."),
            _field(
                name="dipendente_id",
                label="Dipendente / Utente",
                data_type="int",
                description="FK interna al dipendente; usata come equivalente conservativo di `utente_id`.",
                aliases=["utente_id", "employee_id"],
            ),
            _field(
                name="data_inizio",
                label="Data inizio",
                data_type="datetime",
                description="Data e ora di inizio della richiesta assenza.",
                aliases=["Data_x0020_inizio", "DATAINIZIO", "data", "inizio"],
            ),
            _field(
                name="data_fine",
                label="Data fine",
                data_type="datetime",
                description="Data e ora di fine della richiesta assenza.",
                aliases=["Datafine", "fine"],
            ),
            _field(
                name="tipo_assenza",
                label="Tipo assenza",
                data_type="string",
                description="Categoria assenza: ferie, permesso, malattia, ecc.",
                aliases=["Tipoassenza", "tipo", "category"],
            ),
            _field(
                name="motivazione_richiesta",
                label="Motivazione",
                data_type="string",
                description="Motivazione libera inserita dall'utente.",
                aliases=["Motivazionerichiesta", "motivazione"],
            ),
            _field(
                name="moderation_status",
                label="Stato approvazione",
                data_type="int",
                description="Stato tecnico workflow di approvazione della richiesta.",
                aliases=["ModerationStatus", "{ModerationStatus}", "status_approvazione"],
            ),
            _field(
                name="capo_reparto_id",
                label="Capo reparto",
                data_type="int",
                description="Responsabile approvatore associato alla richiesta.",
                aliases=["capo", "approvatore_id", "capo_id"],
            ),
            _field(
                name="capo_email",
                label="Caporeparto email",
                data_type="string",
                description="Email ereditata dal caporeparto selezionato nella richiesta.",
                is_virtual=True,
                aliases=["CAR", "capo_reparto_email", "responsabile_email"],
            ),
            _field(
                name="dipendente_email",
                label="Dipendente email",
                data_type="string",
                db_column="email_esterna",
                description="Email del dipendente collegata alla richiesta assenza.",
                aliases=["Email", "email", "email_esterna", "richiedente_email"],
            ),
            _field(
                name="salta_approvazione",
                label="Salta approvazione",
                data_type="bool",
                db_column="salta_approvazione",
                description="Flag che indica se la richiesta e' stata creata bypassando il flusso approvativo.",
                aliases=["Salta_x0020_approvazione", "SALTAAPPROVAZIONE", "skip_approval"],
            ),
        ],
    },
    "tasks": {
        "code": "tasks",
        "label": "Tasks",
        "source_app": "tasks",
        "table_name": "tasks_task",
        "pk_field": "id",
        "supported_operations": ["insert", "update"],
        "description": "Task ORM Django del portale. I nomi reali colonna sono in inglese.",
        "fields": [
            _field(name="id", label="ID", data_type="int", description="Chiave primaria del task.", aliases=["task_id"]),
            _field(
                name="title",
                label="Titolo",
                data_type="string",
                description="Titolo sintetico del task.",
                aliases=["titolo", "task_title", "subject"],
            ),
            _field(
                name="status",
                label="Stato",
                data_type="string",
                description="Stato operativo del task.",
                aliases=["stato", "task_status"],
            ),
            _field(
                name="priority",
                label="Priorita'",
                data_type="string",
                description="Priorita' del task.",
                aliases=["priorita", "task_priority"],
            ),
            _field(
                name="assigned_to_id",
                label="Assegnato a",
                data_type="int",
                description="Utente Django assegnatario del task.",
                aliases=["assigned_to", "assegnato_a", "owner_id"],
            ),
            _field(
                name="project_id",
                label="Progetto",
                data_type="int",
                description="Progetto collegato al task, se presente.",
                aliases=["project", "progetto"],
            ),
            _field(
                name="due_date",
                label="Scadenza",
                data_type="date",
                description="Data scadenza del task.",
                aliases=["deadline", "data_scadenza"],
            ),
        ],
    },
    "assets": {
        "code": "assets",
        "label": "Assets",
        "source_app": "assets",
        "table_name": "assets_asset",
        "pk_field": "id",
        "supported_operations": ["insert", "update"],
        "description": (
            "Asset ORM Django. Il concetto logico di `codice` e' mappato a `asset_tag`; "
            "`sede` e' mappata conservativamente su `assignment_location`."
        ),
        "fields": [
            _field(name="id", label="ID", data_type="int", description="Chiave primaria asset.", aliases=["asset_id"]),
            _field(
                name="asset_tag",
                label="Codice asset",
                data_type="string",
                description="Codice univoco asset visibile in inventario.",
                aliases=["codice", "code", "tag", "asset_code"],
            ),
            _field(name="name", label="Nome", data_type="string", description="Nome asset.", aliases=["nome_asset"]),
            _field(
                name="asset_category_id",
                label="Categoria",
                data_type="int",
                description="Categoria asset configurata nel portale.",
                aliases=["category", "categoria"],
            ),
            _field(
                name="status",
                label="Stato",
                data_type="string",
                description="Stato ciclo di vita asset.",
                aliases=["stato", "asset_status"],
            ),
            _field(
                name="assignment_location",
                label="Sede / Posizione",
                data_type="string",
                description="Posizione o sede operativa dell'asset.",
                aliases=["sede", "ubicazione", "posizione", "location"],
            ),
            _field(
                name="assigned_legacy_user_id",
                label="Assegnato a",
                data_type="int",
                description="Legacy user assegnatario dell'asset, se presente.",
                aliases=["assegnatario_id", "utente_id", "assigned_to"],
            ),
        ],
    },
    "tickets": {
        "code": "tickets",
        "label": "Tickets",
        "source_app": "tickets",
        "table_name": "tickets_ticket",
        "pk_field": "id",
        "supported_operations": ["insert", "update"],
        "description": "Ticket ORM Django per IT e manutenzione.",
        "fields": [
            _field(name="id", label="ID", data_type="int", description="Chiave primaria ticket.", aliases=["ticket_id"]),
            _field(
                name="titolo",
                label="Titolo",
                data_type="string",
                description="Titolo del ticket.",
                aliases=["title", "subject"],
            ),
            _field(
                name="stato",
                label="Stato",
                data_type="string",
                description="Stato workflow del ticket.",
                aliases=["status", "ticket_status"],
            ),
            _field(
                name="priorita",
                label="Priorita'",
                data_type="string",
                description="Priorita' del ticket.",
                aliases=["priority", "ticket_priority"],
            ),
            _field(
                name="richiedente_legacy_user_id",
                label="Richiedente",
                data_type="int",
                description="Legacy user che ha aperto il ticket.",
                aliases=["richiedente_id", "requester_id", "utente_id"],
            ),
            _field(
                name="assegnato_a",
                label="Assegnato a",
                data_type="string",
                description="Nome libero dell'assegnatario corrente.",
                aliases=["assigned_to", "assegnatario", "owner"],
            ),
            _field(
                name="categoria",
                label="Categoria",
                data_type="string",
                description="Categoria ticket.",
                aliases=["category"],
            ),
        ],
    },
    "anomalie": {
        "code": "anomalie",
        "label": "Anomalie",
        "source_app": "anomalie",
        "table_name": "anomalie",
        "pk_field": "id",
        "supported_operations": ["insert", "update"],
        "description": (
            "Anomalie legacy su SQL Server. Il catalogo espone solo colonne reali correnti: "
            "`OP` e `PN` sono mappati rispettivamente a `ex_op_nominativo` e `seriale`."
        ),
        "fields": [
            _field(name="id", label="ID", data_type="int", description="Chiave primaria anomalia.", aliases=["anomalia_id"]),
            _field(
                name="ex_op_nominativo",
                label="OP",
                data_type="string",
                description="Ordine di produzione in formato testuale.",
                aliases=["op", "ordine_produzione", "op_id", "exopnominativo"],
            ),
            _field(
                name="op_lookup_id",
                label="OP lookup",
                data_type="int",
                description="Lookup tecnico verso ordini di produzione.",
                aliases=["op_lookup", "op_lookupid", "OP_x002d_IDLookupId"],
            ),
            _field(
                name="seriale",
                label="PN / Seriale",
                data_type="string",
                description="Riferimento tecnico disponibile a schema, usato come mapping conservativo del PN.",
                aliases=["pn", "sn", "part_number"],
            ),
            _field(
                name="avanzamento",
                label="Stato",
                data_type="string",
                description="Stato avanzamento dell'anomalia.",
                aliases=["status", "stato"],
            ),
            _field(
                name="chiudere",
                label="Da chiudere",
                data_type="bool",
                description="Flag booleano di chiusura anomalia.",
                aliases=["chiusa", "close", "da_chiudere"],
            ),
            _field(
                name="created_by",
                label="Responsabile / Autore",
                data_type="int",
                db_column="created_by_user_id",
                description="Utente autore disponibile nello schema corrente.",
                aliases=["created_by_user_id", "autore", "responsabile", "legacy_user_id"],
            ),
            _field(
                name="ordine_id",
                label="Ordine interno",
                data_type="int",
                description="Collegamento interno aggiuntivo presente nel database attivo.",
                aliases=["ordine_interno", "order_id"],
            ),
        ],
    },
}


def _normalize_code(code: str | None) -> str:
    return str(code or "").strip().lower()


def _clone_source(source: dict[str, object]) -> dict[str, object]:
    return deepcopy(source)


def get_registered_sources() -> list[dict[str, object]]:
    return [_clone_source(source) for source in _SOURCE_REGISTRY.values()]


def get_source_definition(code: str | None) -> dict[str, object] | None:
    source = _SOURCE_REGISTRY.get(_normalize_code(code))
    if source is None:
        return None
    return _clone_source(source)


def get_source_choices() -> list[tuple[str, str]]:
    return [(source["code"], source["label"]) for source in get_registered_sources()]


def get_source_fields(code: str | None) -> list[dict[str, object]]:
    source = get_source_definition(code)
    if source is None:
        return []
    return list(source.get("fields", []))


def _filter_fields(code: str | None, flag_name: str) -> list[dict[str, object]]:
    return [field for field in get_source_fields(code) if bool(field.get(flag_name))]


def get_trigger_fields(code: str | None) -> list[dict[str, object]]:
    return _filter_fields(code, "usable_in_trigger")


def get_condition_fields(code: str | None) -> list[dict[str, object]]:
    return _filter_fields(code, "usable_in_condition")


def get_template_fields(code: str | None) -> list[dict[str, object]]:
    return _filter_fields(code, "usable_in_template")


def get_action_mapping_fields(code: str | None) -> list[dict[str, object]]:
    return _filter_fields(code, "usable_in_action_mapping")


def build_placeholder_examples(code: str | None) -> list[str]:
    return [f"{{{field['name']}}}" for field in get_template_fields(code)]
