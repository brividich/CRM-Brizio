# Check Flask -> Django

Audit automatico di risoluzione URL: ogni path Flask (con parametri sostituiti da valori sample) viene risolto con il router Django.

Totale route Flask analizzate: 62
Route risolte da Django: 62
Route non risolte: 0

## Dettaglio

| Stato | Methods | Flask path | Sample path | View Django |
|---|---|---|---|---|
| COVERED | GET,POST | `/` | `/` | `dashboard` |
| COVERED | GET | `/` | `/` | `dashboard` |
| COVERED | GET,POST | `/admin` | `/admin` | `legacy_admin_entry` |
| COVERED | GET | `/admin/anagrafica` | `/admin/anagrafica` | `legacy_admin_dispatch` |
| COVERED | POST | `/admin/anagrafica/<int:dip_id>/salva` | `/admin/anagrafica/1/salva` | `legacy_admin_dispatch` |
| COVERED | GET | `/admin/anagrafica/sync_ad` | `/admin/anagrafica/sync_ad` | `legacy_admin_dispatch` |
| COVERED | POST | `/admin/api/permessi/bulk` | `/admin/api/permessi/bulk` | `legacy_admin_dispatch` |
| COVERED | POST | `/admin/api/permessi/toggle` | `/admin/api/permessi/toggle` | `legacy_admin_dispatch` |
| COVERED | POST | `/admin/api/pulsanti/create` | `/admin/api/pulsanti/create` | `legacy_admin_dispatch` |
| COVERED | POST | `/admin/api/pulsanti/delete` | `/admin/api/pulsanti/delete` | `legacy_admin_dispatch` |
| COVERED | POST | `/admin/api/pulsanti/update` | `/admin/api/pulsanti/update` | `legacy_admin_dispatch` |
| COVERED | POST | `/admin/delete_fotocard/<int:user_id>` | `/admin/delete_fotocard/1` | `legacy_admin_dispatch` |
| COVERED | GET | `/admin/export_utenti` | `/admin/export_utenti` | `legacy_admin_dispatch` |
| COVERED | GET | `/admin/force_migrations` | `/admin/force_migrations` | `legacy_admin_dispatch` |
| COVERED | GET | `/admin/gestione_completa` | `/admin/gestione_completa` | `legacy_admin_dispatch` |
| COVERED | GET,POST | `/admin/gestione_pulsanti` | `/admin/gestione_pulsanti` | `legacy_admin_dispatch` |
| COVERED | GET | `/admin/gestione_ruoli` | `/admin/gestione_ruoli` | `legacy_admin_dispatch` |
| COVERED | POST | `/admin/gestione_ruoli` | `/admin/gestione_ruoli` | `legacy_admin_dispatch` |
| COVERED | GET | `/admin/gestione_utenti` | `/admin/gestione_utenti` | `legacy_admin_dispatch` |
| COVERED | GET | `/admin/log-audit` | `/admin/log-audit` | `legacy_admin_dispatch` |
| COVERED | POST | `/admin/modifica_info` | `/admin/modifica_info` | `legacy_admin_dispatch` |
| COVERED | POST | `/admin/modifica_ruoli_massivo` | `/admin/modifica_ruoli_massivo` | `legacy_admin_dispatch` |
| COVERED | POST | `/admin/modifica_ruolo` | `/admin/modifica_ruolo` | `legacy_admin_dispatch` |
| COVERED | POST | `/admin/modifica_ruolo_singolo` | `/admin/modifica_ruolo_singolo` | `legacy_admin_dispatch` |
| COVERED | GET,POST | `/admin/permessi` | `/admin/permessi` | `legacy_admin_dispatch` |
| COVERED | POST | `/admin/permessi/aggiungi` | `/admin/permessi/aggiungi` | `legacy_admin_dispatch` |
| COVERED | POST | `/admin/reset_password_scheda` | `/admin/reset_password_scheda` | `legacy_admin_dispatch` |
| COVERED | GET | `/admin/ricarica_capi` | `/admin/ricarica_capi` | `legacy_admin_dispatch` |
| COVERED | GET | `/admin/sync/pending-anomalie` | `/admin/sync/pending-anomalie` | `legacy_admin_dispatch` |
| COVERED | GET | `/admin/sync/<lista>` | `/admin/sync/x` | `legacy_admin_dispatch` |
| COVERED | GET | `/admin/sync_info_personali` | `/admin/sync_info_personali` | `legacy_admin_dispatch` |
| COVERED | GET | `/admin/sync_mansioni` | `/admin/sync_mansioni` | `legacy_admin_dispatch` |
| COVERED | GET | `/admin/test` | `/admin/test` | `legacy_admin_dispatch` |
| COVERED | POST | `/admin/upload_fotocard` | `/admin/upload_fotocard` | `legacy_admin_dispatch` |
| COVERED | GET | `/admin/utente/<int:user_id>` | `/admin/utente/1` | `legacy_admin_dispatch` |
| COVERED | GET | `/admin/utente/<int:user_id>/pdf` | `/admin/utente/1/pdf` | `legacy_admin_dispatch` |
| COVERED | GET | `/anomalie-menu` | `/anomalie-menu` | `anomalie_menu` |
| COVERED | GET | `/api/anomalie/anomalie` | `/api/anomalie/anomalie` | `api_anomalie_anomalie` |
| COVERED | GET | `/api/anomalie/campi` | `/api/anomalie/campi` | `api_anomalie_campi` |
| COVERED | GET | `/api/anomalie/db/anomalie` | `/api/anomalie/db/anomalie` | `api_anomalie_db_anomalie` |
| COVERED | GET | `/api/anomalie/db/ordini` | `/api/anomalie/db/ordini` | `api_anomalie_db_ordini` |
| COVERED | GET | `/api/anomalie/ordini` | `/api/anomalie/ordini` | `api_anomalie_ordini` |
| COVERED | POST | `/api/anomalie/salva` | `/api/anomalie/salva` | `api_anomalie_salva` |
| COVERED | POST | `/api/anomalie/sync` | `/api/anomalie/sync` | `api_anomalie_sync` |
| COVERED | GET | `/assenze/` | `/assenze/` | `assenze_menu` |
| COVERED | POST | `/assenze/aggiorna_consenso/<int:item_id>` | `/assenze/aggiorna_consenso/1` | `assenze_aggiorna_consenso` |
| COVERED | GET | `/assenze/api/eventi` | `/assenze/api/eventi` | `assenze_api_eventi` |
| COVERED | GET | `/assenze/calendario` | `/assenze/calendario` | `assenze_calendario` |
| COVERED | GET | `/assenze/gestione_assenze` | `/assenze/gestione_assenze` | `assenze_gestione` |
| COVERED | POST | `/assenze/invio` | `/assenze/invio` | `assenze_invio` |
| COVERED | GET | `/assenze/richiesta_assenze` | `/assenze/richiesta_assenze` | `assenze_richiesta` |
| COVERED | GET,POST | `/cambia-password` | `/cambia-password` | `cambia_password_legacy_noslash` |
| COVERED | GET | `/check` | `/check` | `legacy_flask_check` |
| COVERED | GET | `/dashboard` | `/dashboard` | `dashboard_home` |
| COVERED | GET | `/gestione-anomalie` | `/gestione-anomalie` | `gestione_anomalie_page` |
| COVERED | GET,POST | `/gestione-anomalie/apertura` | `/gestione-anomalie/apertura` | `legacy_gestione_anomalie_apertura` |
| COVERED | GET,POST | `/gestione-anomalie/apertura/anomalie` | `/gestione-anomalie/apertura/anomalie` | `legacy_gestione_anomalie_apertura_anomalie` |
| COVERED | POST | `/gestione_utenti/modifica/<int:user_id>` | `/gestione_utenti/modifica/1` | `legacy_gestione_utenti_modifica` |
| COVERED | GET | `/logout` | `/logout` | `logout_legacy_noslash` |
| COVERED | POST | `/modifica_capo` | `/modifica_capo` | `legacy_modifica_capo` |
| COVERED | POST | `/modifica_info_completa` | `/modifica_info_completa` | `legacy_modifica_info_completa` |
| COVERED | GET | `/richieste` | `/richieste` | `richieste` |

## Copertura effettiva

- Route coperte da view Django native: 27
- Route coperte tramite layer compatibilit? legacy: 35
- Nota: le route legacy `POST` sotto `/admin/...` sono compatibili a livello URL ma, se non mappate a una feature nuova, restituiscono risposta `410` con messaggio di endpoint dismesso.

### Route in compatibilit? legacy

- `GET,POST` ``/admin`` -> `legacy_admin_entry`
- `GET` ``/admin/anagrafica`` -> `legacy_admin_dispatch`
- `POST` ``/admin/anagrafica/<int:dip_id>/salva`` -> `legacy_admin_dispatch`
- `GET` ``/admin/anagrafica/sync_ad`` -> `legacy_admin_dispatch`
- `POST` ``/admin/api/permessi/bulk`` -> `legacy_admin_dispatch`
- `POST` ``/admin/api/permessi/toggle`` -> `legacy_admin_dispatch`
- `POST` ``/admin/api/pulsanti/create`` -> `legacy_admin_dispatch`
- `POST` ``/admin/api/pulsanti/delete`` -> `legacy_admin_dispatch`
- `POST` ``/admin/api/pulsanti/update`` -> `legacy_admin_dispatch`
- `POST` ``/admin/delete_fotocard/<int:user_id>`` -> `legacy_admin_dispatch`
- `GET` ``/admin/export_utenti`` -> `legacy_admin_dispatch`
- `GET` ``/admin/force_migrations`` -> `legacy_admin_dispatch`
- `GET` ``/admin/gestione_completa`` -> `legacy_admin_dispatch`
- `GET,POST` ``/admin/gestione_pulsanti`` -> `legacy_admin_dispatch`
- `GET` ``/admin/gestione_ruoli`` -> `legacy_admin_dispatch`
- `POST` ``/admin/gestione_ruoli`` -> `legacy_admin_dispatch`
- `GET` ``/admin/gestione_utenti`` -> `legacy_admin_dispatch`
- `GET` ``/admin/log-audit`` -> `legacy_admin_dispatch`
- `POST` ``/admin/modifica_info`` -> `legacy_admin_dispatch`
- `POST` ``/admin/modifica_ruoli_massivo`` -> `legacy_admin_dispatch`
- `POST` ``/admin/modifica_ruolo`` -> `legacy_admin_dispatch`
- `POST` ``/admin/modifica_ruolo_singolo`` -> `legacy_admin_dispatch`
- `GET,POST` ``/admin/permessi`` -> `legacy_admin_dispatch`
- `POST` ``/admin/permessi/aggiungi`` -> `legacy_admin_dispatch`
- `POST` ``/admin/reset_password_scheda`` -> `legacy_admin_dispatch`
- `GET` ``/admin/ricarica_capi`` -> `legacy_admin_dispatch`
- `GET` ``/admin/sync/pending-anomalie`` -> `legacy_admin_dispatch`
- `GET` ``/admin/sync/<lista>`` -> `legacy_admin_dispatch`
- `GET` ``/admin/sync_info_personali`` -> `legacy_admin_dispatch`
- `GET` ``/admin/sync_mansioni`` -> `legacy_admin_dispatch`
- `GET` ``/admin/test`` -> `legacy_admin_dispatch`
- `POST` ``/admin/upload_fotocard`` -> `legacy_admin_dispatch`
- `GET` ``/admin/utente/<int:user_id>`` -> `legacy_admin_dispatch`
- `GET` ``/admin/utente/<int:user_id>/pdf`` -> `legacy_admin_dispatch`
- `GET` ``/check`` -> `legacy_flask_check`