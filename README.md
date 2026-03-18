# Integrazione Octopus Energy Italy per Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=utenti&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=%24.octopus_energy_it.total)

> 🎁 Stai scegliendo una nuova wallbox? Approfitta del **10% di sconto** su Trydan o Trydan Pro nello store ufficiale V2C (https://v2charge.com/store/it/) con il codice `INTEGRATIONTRYDAN10`

> 🎁 Se devi attivare un nuovo abbonamento con Octopus Energy puoi usare questo [link](https://octopusenergy.it/octo-friends/airy-queen-959): otterrai **uno sconto fino a 50 €**

Questa integrazione personalizzata utilizza le API GraphQL di Octopus Energy Italy per portare in Home Assistant saldi, tariffe, punti di prelievo, dispositivi SmartFlex e preferenze di ricarica.

La documentazione ufficiale è disponibile sul [developer portal Octopus Energy Italy](https://developer.oeit-kraken.energy/).

Se utilizzi **Intelligent Octopus** con una **wallbox V2C** ([https://v2charge.com/it/](https://v2charge.com/it/)), questa integrazione ti consente di collegare **Home Assistant** al servizio **Octopus Energy Italy**, delegando a **Intelligent Octopus** la gestione ottimizzata delle ricariche in base agli orari energetici più convenienti e ai target di ricarica impostati direttamente nel servizio.

A differenza dell'integrazione nativa tra V2C e Home Assistant, questa soluzione utilizza **Intelligent Octopus** come motore di ottimizzazione, permettendo di monitorare e controllare da Home Assistant i target di ricarica e le sessioni gestite automaticamente da Octopus Energy.

Se vuoi connettere Home Assistant direttamente al cloud V2C, prova l'integrazione complementare [HomeAssistant-V2C-Cloud](https://github.com/samuelebistoletti/HomeAssistant-V2C-Cloud): porta in HA telemetrie e controlli nativi della wallbox.

Per saperne di più sui miei progetti vai su https://samuele.bistoletti.me/.

---

## Caratteristiche principali

- **Copertura completa dei dati italiani** – recupero di account, ledger, proprietà, punti di prelievo, prodotti e finestre SmartFlex pubblicati dalle API ufficiali di Octopus Energy Italy.
- **Gestione multi-account** – rilevamento automatico di tutti i conti collegati alle credenziali e suddivisione dei dati per ciascuno di essi.
- **Tariffe dettagliate per luce e gas** – esposizione del prodotto attivo, dei prezzi base/F2/F3, delle quote fisse, dell'unità di misura (incluso il prezzo gas in €/m³) e dei link ai termini contrattuali.
- **Monitoraggio POD e PDR** – stato fornitura, date di attivazione, presenza del contatore smart e motivazioni di eventuale cessazione.
- **Funzionalità SmartFlex** – stato dispositivi, limiti di carica, finestre di dispatch correnti/future e capacità della batteria del veicolo.
- **Interfaccia bilingue** – nomi delle entità e stati di POD, PDR ed EV disponibili in italiano e inglese con descrizioni leggibili.
- **Aggiornamenti integrati in Home Assistant** – utilizzo del DataUpdateCoordinator, registrazione automatica delle entità e servizi dedicati per aggiornare le preferenze di ricarica.

## Prerequisiti

- Account cliente Octopus Energy Italy con accesso al portale clienti.
- Home Assistant 2025.4.0 o successivo.
- Facoltativo: attivare il debug in `configuration.yaml` per indagare eventuali problemi API.

```yaml
logger:
  logs:
    custom_components.octopus_energy_it: debug
```

## Installazione

### HACS (consigliata)

1. In HACS cerca "Octopus Energy Italy" e installa l'integrazione.
2. Riavvia Home Assistant quando richiesto.
3. Configura l'integrazione da **Impostazioni → Dispositivi e servizi → Aggiungi integrazione**.

### Installazione manuale

1. Copia la cartella `custom_components/octopus_energy_it` nella directory `custom_components` della tua istanza Home Assistant.
2. Riavvia Home Assistant.
3. Segui la procedura guidata da **Impostazioni → Dispositivi e servizi → Aggiungi integrazione**.

## Configurazione iniziale

1. Seleziona **Octopus Energy Italy** tra le integrazioni disponibili.
2. Inserisci e-mail e password utilizzate sul portale clienti Octopus Energy Italy.
3. La procedura convalida le credenziali, recupera i numeri di conto e li memorizza nella config entry.
4. Le entità vengono create dopo il primo aggiornamento del coordinatore (circa 60 secondi).

## Modello dati gestito

- **Accounts & Ledgers** – saldi per elettricità, gas, calore e altri ledger (es. canone TV).
- **Proprietà e punti di prelievo** – POD, PDR, stato di fornitura, date di enrolment, dati smart meter e motivazioni di cancellazione.
- **Prodotti** – prodotti attivi e storici con prezzi dettagliati, oneri, unità, tipologia tariffaria, termini contrattuali e periodo di validità.
- **Dispositivi & preferenze** – dispositivi SmartFlex, stato di sospensione, programmi di ricarica e target percentuale.
- **Dispatch SmartFlex** – finestre di carica pianificate e completate per automazioni di ricarica intelligente.

## Entità esposte

### Sensori binari

- `binary_sensor.octopus_<account>_intelligent_dispatching` – `on` se è attiva una finestra di dispatch in questo momento.

### Sensori

**Tariffe e prodotti**

| Entità | Unità | Attributi extra |
| --- | --- | --- |
| `sensor.octopus_<account>_electricity_price` | €/kWh | — |
| `sensor.octopus_<account>_electricity_price_f2` | €/kWh | — |
| `sensor.octopus_<account>_electricity_price_f3` | €/kWh | — |
| `sensor.octopus_<account>_electricity_product` | testo | `account_number`, `product_code`, `product_type`, `product_description`, `agreement_id`, `valid_from`, `valid_to`, `is_time_of_use`, `terms_url`, `price_base`, `price_f2`, `price_f3`, `price_unit`, `standing_charge_annual`, `standing_charge_units`, `linked_agreements` |
| `sensor.octopus_<account>_electricity_standing_charge` | €/anno | — |
| `sensor.octopus_<account>_gas_price` | €/m³ | — |
| `sensor.octopus_<account>_gas_product` | testo | `account_number`, `product_code`, `product_type`, `product_description`, `agreement_id`, `valid_from`, `valid_to`, `terms_url`, `price_base`, `price_unit`, `standing_charge_annual`, `standing_charge_units`, `linked_agreements` |
| `sensor.octopus_<account>_gas_standing_charge` | €/anno | — |

**Letture e stato dei contatori**

| Entità | Unità | Attributi extra |
| --- | --- | --- |
| `sensor.octopus_<account>_electricity_last_reading` | kWh | `period_start`, `period_end`, `data_source`, `unit_of_measurement`, `register_start_value`, `register_end_value` |
| `sensor.octopus_<account>_electricity_last_daily_reading` | kWh | `period_start`, `period_end`, `data_source`, `unit_of_measurement`, `register_start_value`, `register_end_value` |
| `sensor.octopus_<account>_electricity_last_reading_date` | data | — |
| `sensor.octopus_<account>_electricity_meter_status` | testo | `account_number`, `pod`, `supply_point_id`, `enrollment_status`, `enrollment_started_at`, `supply_started_at`, `is_smart_meter`, `cancellation_reason` |
| `sensor.octopus_<account>_gas_last_reading` | m³ | `recorded_at`, `measurement_type`, `measurement_source`, `unit_of_measurement` |
| `sensor.octopus_<account>_gas_last_reading_date` | data | — |
| `sensor.octopus_<account>_gas_meter_status` | testo | `account_number`, `pdr`, `enrollment_status`, `enrollment_started_at`, `supply_started_at`, `is_smart_meter`, `cancellation_reason` |

Nota: `electricity_last_reading` è la lettura cumulativa del contatore (adatta alla dashboard Energia di HA), mentre `electricity_last_daily_reading` rappresenta il consumo dell'ultimo intervallo giornaliero.

**Saldi e contratti**

- `sensor.octopus_<account>_electricity_balance`, `sensor.octopus_<account>_gas_balance`, `sensor.octopus_<account>_heat_balance` e `sensor.octopus_<account>_<ledger>_balance` riportano i saldi monetari forniti dall'API.
- `sensor.octopus_<account>_electricity_contract_start`, `_electricity_contract_end` e `_electricity_contract_days_until_expiry` espongono rispettivamente data di attivazione, data di termine e giorni residui del contratto luce (equivalenti disponibili per il gas).
- `sensor.octopus_<account>_vehicle_battery_size` indica la capacità stimata dell'accumulatore e fornisce gli attributi `account_number`, `device_id`, `device_name`, `vehicle_model`, `device_provider`.

**SmartFlex e dispatch**

| Entità | Unità | Attributi extra |
| --- | --- | --- |
| `sensor.octopus_<account>_ev_charge_status` | testo | `account_number`, `device_id`, `device_name`, `device_model`, `device_provider`, `battery_capacity_kwh`, `status_current_state`, `status_connection_state`, `status_is_suspended`, `preferences_mode`, `preferences_unit`, `preferences_target_type`, `allow_grid_export`, `schedules`, `target_day_of_week`, `target_time`, `target_percentage`, `boost_active`, `boost_available`, `last_synced_at` |
| `sensor.octopus_<account>_ev_next_dispatch_start` | timestamp | `end`, `energy_kwh`, `type` — orario di inizio della prossima finestra di carica pianificata |
| `sensor.octopus_<account>_ev_next_dispatch_end` | timestamp | `start`, `energy_kwh`, `type` — orario di fine della prossima finestra di carica pianificata |
| `sensor.octopus_<account>_ev_planned_dispatches` | numero | `dispatches` (lista completa), `current_start`, `current_end` — conteggio delle finestre future; espone anche la finestra attiva corrente |

> I sensori e i controlli dedicati a SmartFlex compaiono solo per i dispositivi Intelligent Octopus supportati.

**Tariffe pubbliche**

Per ogni tariffa riportata sul sito Octopus viene creato un sensore dedicato `sensor.octopus_energy_public_tariffs_<nome_tariffa_slug>`, incluse le offerte PLACET.

| Attributo | Descrizione |
| --- | --- |
| `code` | Codice prodotto Octopus come riportato sul sito |
| `name` | Nome esteso della tariffa |
| `type` | Tipo GraphQL (`ElectricityProduct`, `GasProduct`, ecc.) |
| `product_type` | Categoria della tariffa (residenziale, business, ecc.) |
| `description` | Breve descrizione commerciale |
| `terms_url` | Link ai termini e condizioni ufficiali |
| `charge_f1`, `charge_f2`, `charge_f3` | Prezzi €/kWh o €/Smc per fascia |
| `standing_charge_annual` | Quota fissa annuale nella valuta originaria |

I prezzi vengono aggiornati ogni ora. Se il sito delle tariffe non risponde, il retry avviene automaticamente ogni 5 minuti utilizzando l'ultimo valore valido come cache; i sensori non passano mai in stato Unknown durante un'interruzione temporanea del sito.

### Number

- `number.octopus_<account>_<device_id>_charge_target` – imposta il target di ricarica SmartFlex (10–100%, passi da 1). L'aggiornamento viene propagato al coordinatore condiviso, che mantiene coerenti sensori e controlli.

### Select

- `select.octopus_<account>_<device_id>_target_time_select` – seleziona l'orario di completamento SmartFlex. Le opzioni sono generate in base ai limiti `timeFrom`/`timeTo` e allo `timeStep` restituiti dall'API.

### Switch

- `switch.octopus_<account>_<device_id>_ev_charge_smart_control` – sospende o riattiva il controllo intelligente del dispositivo. Contiene `<device_id>` per supportare correttamente più veicoli sullo stesso account.
- `switch.octopus_<account>_<device_id>_boost_charge` – avvia o annulla il boost immediato quando disponibile (solo per dispositivi con `deviceType` `ELECTRIC_VEHICLES` o `CHARGE_POINTS`).

### Servizi

- `octopus_energy_it.set_device_preferences`
  - `device_id`: ID del dispositivo (obbligatorio)
  - `target_percentage`: valore 10–100 con passi da 1 (obbligatorio)
  - `target_time`: orario di conclusione (`HH:MM`, 04:00–17:00) (obbligatorio)

## Sviluppo locale

### Ambiente di sviluppo

```bash
# Installa le dipendenze di sviluppo (ruff, pytest, ecc.)
bash scripts/setup

# Avvia un'istanza Home Assistant locale su http://localhost:8123
docker-compose up

# Segui i log del container
docker-compose logs -f homeassistant
```

### Test automatici

La suite di test usa `pytest` e `pytest-asyncio` e non richiede una installazione di Home Assistant (tutte le dipendenze HA vengono simulate tramite stub).

```bash
# Installa le dipendenze di test
pip install -r requirements_test.txt

# Esegui tutti i test
python -m pytest tests/

# Con output verboso
python -m pytest tests/ -v

# Solo un file di test
python -m pytest tests/test_api_client.py -v
```

I test coprono:

| File | Cosa testa |
| --- | --- |
| `tests/test_api_client.py` | Client GraphQL: autenticazione, token management, fetch dati, mutazioni |
| `tests/test_sensor.py` | Logica sensori: dispatch window, arrotondamenti letture, sensor states |
| `tests/test_switch.py` | Switch: available, is_on (pending/timeout), turn_on/off, coordinator update, boost charge |
| `tests/test_binary_sensor.py` | Binary sensor: finestre attive/future/passate, proprietà available (tutti i rami) |
| `tests/test_coordinator.py` | Coordinator: fetch dati, retry tariffe pubbliche, gestione errori |
| `tests/test_data_processor.py` | Elaborazione dati API: ledger, punti di prelievo, dispatch, tariffe fallback, scadenze contratto, dispositivi, letture elettricità, prodotti disponibili |

### Lint e formattazione

```bash
# Formatta e corregge automaticamente (ruff format + ruff check --fix)
bash scripts/lint
```

## Risoluzione problemi

- Verifica **Strumenti per sviluppatori → Log** per messaggi di errore o avviso.
- Imposta `LOG_API_RESPONSES` o `LOG_TOKEN_RESPONSES` su `True` in `custom_components/octopus_energy_it/const.py` per log estesi (solo per debug temporaneo).
- Se non compaiono entità, assicurati che almeno un POD o PDR sia attivo nell'area clienti Octopus Energy.
- Se le entità degli switch risultano non disponibili dopo un aggiornamento, eliminale dall'**Entity Registry** (filtro "non disponibili") — i nuovi ID includono `<device_id>` per supportare più dispositivi per account.
