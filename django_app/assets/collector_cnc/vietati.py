"""Nomi delle funzioni di scrittura che non devono mai comparire nel package ``drivers``.

È l'elenco unico usato dal controllo statico dei test (``tests_cnc/test_sola_lettura.py``): ogni
identificatore e ogni stringa dei file in ``drivers/`` viene confrontato con ``NOMI_VIETATI``
(uguaglianza esatta) e con ``PREFISSI_VIETATI`` (inizio del nome, maiuscole/minuscole ignorate).
Sta fuori da ``drivers/`` apposta: lì dentro questi nomi non devono comparire nemmeno come testo.

Cosa copre:
- OPC UA (asyncua): scrittura di valori e attributi, chiamata di metodi, modifica dello spazio
  indirizzi, sottoscrizioni che possono scatenare azioni (``ConditionRefresh``, acknowledge);
- Heidenhain LSV2 (pyLSV2): trasferimento e cancellazione di file, selezione ed esecuzione di
  programmi, scrittura di parametri e tabelle, combinazioni di tasti;
- Fanuc FOCAS (Fwlib): ``cnc_wr*`` (scritture), ``cnc_ds*`` (DNC/Data Server), ``pmc_wr*`` (segnali
  PLC), upload/download di programmi, cancellazione e selezione di programmi, reset.

Si aggiunge un nome quando una libreria introduce una nuova funzione di scrittura; non si toglie
mai un nome senza una decisione scritta (ADR in ``docs/``).
"""
from __future__ import annotations

NOMI_VIETATI: frozenset[str] = frozenset({
    # OPC UA
    "write_value", "write_values", "write_attribute", "write_attribute_value", "write_params",
    "set_value", "set_attribute", "set_writable", "set_read_only", "call_method", "call",
    "add_nodes", "add_variable", "add_object", "add_folder", "add_method", "add_reference",
    "delete", "delete_nodes", "delete_references", "ConditionRefresh", "Acknowledge", "Confirm",
    "history_update", "register_nodes", "unregister_nodes", "create_subscription", "subscribe_events",
    "subscribe_data_change", "load_data_type_definitions", "import_xml",
    # Heidenhain LSV2 (pyLSV2, nomi 0.x e 1.x)
    "send_file", "recive_file", "receive_file", "copy_remote_file", "copy_local_file", "move_file",
    "move_local_file", "delete_file", "delete_empty_directory", "make_directory", "change_directory",
    "set_keyboard_access", "send_key_code", "set_machine_parameter", "write_machine_parameter",
    "program_select", "select_program", "program_start", "program_stop", "start_program", "stop_program",
    "set_file_system_attribute", "send_tool_table", "write_plc_memory", "write_tool_table",
    "login_file_transfer",
    # Fanuc FOCAS (funzioni esatte oltre ai prefissi)
    "cnc_reset", "cnc_reset2", "cnc_delete", "cnc_delall", "cnc_search", "cnc_rewind", "cnc_pdf_del",
    "cnc_pdf_slctmain", "cnc_pdf_rename", "cnc_pdf_add", "cnc_pdf_cond", "cnc_wrprogline",
    "cnc_dncstart", "cnc_dnc", "cnc_dncend", "cnc_setpath", "cnc_clrcntinfo", "cnc_prstwkcd",
})

PREFISSI_VIETATI: tuple[str, ...] = (
    "write_", "set_value", "call_method", "delete_", "send_file", "recive_file", "receive_file",
    "cnc_wr", "cnc_ds", "pmc_wr", "cnc_upload", "cnc_download", "cnc_upstart", "cnc_dwnstart",
    "cnc_dnc", "cnc_pdf_", "cnc_del",
)


def vietato(nome: str) -> bool:
    """True se ``nome`` è una funzione di scrittura (nome esatto o prefisso)."""
    basso = nome.lower()
    return nome in NOMI_VIETATI or basso in {n.lower() for n in NOMI_VIETATI} or basso.startswith(PREFISSI_VIETATI)
