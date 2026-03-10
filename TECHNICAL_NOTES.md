# Octopus Energy Italy Integration — Note tecniche

## Panoramica dell'architettura

### Riferimenti API

- Documentazione ufficiale: [developer portal Octopus Energy Italy](https://developer.oeit-kraken.energy/)
- Endpoint GraphQL: `https://api.oeit-kraken.energy/v1/graphql/` — usato tramite `python-graphql-client`

### Componenti principali

| File | Ruolo |
|------|-------|
| `octopus_energy_it.py` | Client GraphQL — autenticazione, refresh token, tutte le chiamate API |
| `__init__.py` | Setup integrazione, `DataUpdateCoordinator`, scraper tariffe pubbliche |
| `entity.py` | Classi base (`OctopusCoordinatorEntity`, `OctopusPublicProductsEntity`, `OctopusDeviceScheduleMixin`) |
| `config_flow.py` | Validazione credenziali e config flow utente |
| `sensor.py` | Prezzi, saldi, letture contatori, dispatch, tariffe pubbliche |
| `switch.py` | Sospensione dispositivi + boost charge |
| `binary_sensor.py` | Rilevamento finestra di dispatch attiva |
| `number.py` | Target percentuale ricarica SmartFlex (10–100%) |
| `select.py` | Selettore orario pronto SmartFlex |
| `const.py` | Dominio, intervalli, costanti token, flag di debug |

### Flusso dati

```
ConfigEntry (email + password)
    → OctopusEnergyIT API client (octopus_energy_it.py)
    → OctopusEnergyITDataUpdateCoordinator (__init__.py)
    → Tutte le piattaforme (sensor, switch, binary_sensor, number, select)
```

### Struttura dati del coordinator

```python
coordinator.data = {
    "account_number": {
        "devices": [...],
        "products": [...],
        "ledgers": [...],
        "properties": [...],
        "planned_dispatches": [...],
        "completed_dispatches": [...],
        "meter_readings": {
            "electricity": [...],
            "gas": [...],
        },
    }
}
```

Tutte le chiavi usano **snake_case**. Non usare varianti camelCase (`plannedDispatches`, `meterReadings`): non esistono più nel codice.

---

## Dettagli implementativi

### Accesso al coordinator

Tutte le piattaforme devono usare questo pattern:

```python
data = hass.data[DOMAIN][entry.entry_id]
coordinator = data["coordinator"]
api = data["api"]
```

Non creare coordinator separati per piattaforma. Il coordinator e il client API sono istanze singole condivise in `hass.data[DOMAIN][entry.entry_id]`.

### Token management

La classe `TokenManager` in `octopus_energy_it.py` gestisce tutto il ciclo di vita del token:

- Refresh automatico quando mancano meno di 5 minuti alla scadenza
- Fallback su intervallo fisso di 50 minuti se il token non è un JWT decodificabile
- Token memorizzati **solo in memoria** (mai su disco o config entry)
- Non chiamare `_get_graphql_client()` direttamente dalle piattaforme — usare sempre i metodi pubblici del client API (es. `api.update_boost_charge()`) che gestiscono il refresh automatico

### Localizzazione ed entità

Tutte le entità espongono `_attr_translation_key`. I file di traduzione sono in `translations/it.json` e `translations/en.json`. Le funzioni `_normalize_supply_status` e `_normalize_ev_status` convertono gli stati grezzi del backend Kraken in slug leggibili.

### Switch: unique ID e disponibilità

Gli switch includono `<device_id>` nel `unique_id` per supportare correttamente più dispositivi (es. due veicoli elettrici) sullo stesso account:

- `{DOMAIN}_{account_number}_{device_id}_ev_charge_smart_control`
- `{DOMAIN}_{account_number}_{device_id}_boost_charge`

Il boost switch è disponibile solo per dispositivi con `deviceType` in `["ELECTRIC_VEHICLES", "CHARGE_POINTS"]` e solo quando il dispositivo è `LIVE` con `SMART_CONTROL_CAPABLE`, stato `BOOST`, o in `BOOST_CHARGING`.

### Mixin schedule dispositivo (number.py, select.py)

La logica condivisa per accedere e aggiornare lo schedule di un dispositivo SmartFlex è in `OctopusDeviceScheduleMixin` (`entity.py`). Fornisce:

- `_current_device()` — recupera il dict del dispositivo dal coordinator
- `_current_schedule()` — primo entry degli schedule dal dict `preferences`
- `_schedule_setting()` — limiti dello schedule da `preferenceSetting`
- `_current_target_percentage()` / `_current_target_time()` — valori attuali
- `_update_local_schedule()` — aggiorna i dati locali del coordinator dopo una mutazione, così la UI rimane coerente tra un poll e l'altro

Non duplicare questa logica in `number.py` o `select.py`.

### Tariffe pubbliche e retry

Lo scraper in `__init__.py` legge `https://octopusenergy.it/le-nostre-tariffe` ogni ora, estraendo `__NEXT_DATA__` JSON e offerte PLACET dall'HTML.

Il meccanismo di retry usa `hass.async_call_later()` (un timer one-shot affidabile). **Non** modificare `coordinator.update_interval` a runtime: la modifica non ha effetto sulla schedulazione già attiva del coordinator.

Quando lo scraping fallisce:
1. Se esiste una cache, viene restituita con un warning — i sensori mantengono il valore precedente
2. Viene schedulato un retry dopo 5 minuti (`PUBLIC_PRODUCTS_RETRY_DELAY = 300`)
3. Al successivo retry riuscito, la cache viene aggiornata e il retry annullato

Il `public_products_retry_unsub` viene cancellato in `async_unload_entry` per evitare callback orfani.

Un solo device pubblico per istanza HA (tracciato in `hass.data[DOMAIN]["public_owner"]`), indipendentemente da quante config entry sono caricate.

### Gestione errori del coordinator principale

Quando tutti gli account falliscono il fetch, il coordinator solleva `UpdateFailed` (non restituisce dati obsoleti con status verde). Questo fa segnare `last_update_success=False` e mostra il problema nell'UI di HA.

```python
if not all_accounts_data:
    raise UpdateFailed("Failed to fetch data for any account")
```

Gli account che falliscono individualmente vengono loggati ma non bloccano il fetch degli altri.

---

## Flag di debug (const.py)

Da impostare temporaneamente durante il debug:

```python
LOG_API_RESPONSES = True   # logga tutte le risposte GraphQL complete
LOG_TOKEN_RESPONSES = True  # logga operazioni di login e refresh token
DEBUG_ENABLED = True        # flag debug generale
```

Logging da `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.octopus_energy_it: debug
    custom_components.octopus_energy_it.octopus_energy_it: debug
    custom_components.octopus_energy_it.switch: debug
```

---

## Test

### Struttura

I test sono in `tests/` e non richiedono un'installazione di Home Assistant reale — tutte le dipendenze vengono simulate da stub in `tests/conftest.py`.

```
tests/
├── conftest.py           # stub HA + fixture condivise
├── test_api_client.py    # client GraphQL (82 test)
├── test_sensor.py        # logica sensori (27 test)
├── test_switch.py        # switch: unique_id, disponibilità (13 test)
├── test_binary_sensor.py # binary sensor dispatching (14 test)
└── test_coordinator.py   # coordinator e tariffe pubbliche (58 test)
```

### Esecuzione

```bash
pip install -r requirements_test.txt
python -m pytest tests/
python -m pytest tests/ -v          # verboso
python -m pytest tests/test_sensor.py -v  # singolo file
```

### Infrastruttura stub

`conftest.py` installa gli stub in `sys.modules` prima di qualsiasi import dei moduli dell'integrazione. Il pattern cruciale:

```python
# custom_components deve essere registrato come package (con __path__)
# altrimenti le sotto-import falliscono con "not a package"
_oeit = types.ModuleType("custom_components.octopus_energy_it")
_oeit.__path__ = [_oeit_path]
_oeit.__package__ = "custom_components.octopus_energy_it"
sys.modules["custom_components.octopus_energy_it"] = _oeit
```

Il file `const.py` non ha dipendenze HA e viene caricato direttamente da disco (non è necessario uno stub per esso).

### Copertura delle aree critiche

I test coprono esplicitamente:

1. **Correttezza unique_id switch** — due dispositivi dello stesso tipo producono ID distinti
2. **Logica finestra di dispatch** — `_effective_dispatch_window()` con slot attivi vs futuri vs passati
3. **Arrotondamento letture** — 3 decimali per `electricity_last_daily_reading` e `electricity_last_reading`
4. **Retry tariffe pubbliche** — fallback su cache, scheduling del retry, annullamento al successo
5. **Token management** — decode JWT, fallback su intervallo fisso, scadenza, validità

---

## Sicurezza

- I token sono conservati **solo in memoria**, mai persistiti
- Email e password vengono lette dalla config entry e mai loggiate
- Tutta la comunicazione API avviene su HTTPS (endpoint ufficiale Kraken)

---

## Note su breaking change

Quando si modifica un `unique_id` di entità, documentarlo nel `CHANGELOG.md` con le istruzioni per rimuovere le entità orfane dall'Entity Registry di HA. Non aggiungere migration entry per retrocompatibilità: preferire la breaking change esplicita con istruzioni chiare per l'utente.
