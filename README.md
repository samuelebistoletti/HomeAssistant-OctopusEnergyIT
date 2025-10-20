# Integrazione Octopus Energy Italy per Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=utenti&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=%24.octopus_energy_it.total)

Questa integrazione personalizzata utilizza le API GraphQL di Octopus Energy Italy per portare in Home Assistant saldi, tariffe, punti di prelievo, dispositivi SmartFlex e preferenze di ricarica.

*Il progetto è mantenuto dalla community e non è affiliato in alcun modo ad Octopus Energy*

:car: :octopus: Se utilizzi **Intelligent Octopus** con una **wallbox V2C :electric_plug:** ([https://v2charge.com/it/](https://v2charge.com/it/)), questa integrazione ti consente di collegare **Home Assistant** al servizio **Octopus Energy Italy**, delegando a **Intelligent Octopus** la gestione ottimizzata delle ricariche in base agli orari energetici più convenienti e ai target di ricarica impostati direttamente nel servizio.

:zap: A differenza dell’integrazione nativa tra V2C e Home Assistant, questa soluzione utilizza **Intelligent Octopus** come motore di ottimizzazione, permettendo di monitorare e controllare da Home Assistant i target di ricarica e le sessioni gestite automaticamente da Octopus.

:purple_heart: Ti piace l’integrazione?
Puoi sostenere il progetto con una **donazione una tantum o mensile** tramite [GitHub Sponsorship](https://github.com/sponsors/samuelebistoletti)
oppure usare il [link di riferimento Octopus Energy](https://octopusenergy.it/octo-friends/airy-queen-959) per attivare un nuovo abbonamento: otterrai **uno sconto fino a 50 €** :gift:

---

## :sparkles: Caratteristiche principali

- :electric_plug: **Copertura completa dei dati italiani** – recupero di account, ledger, proprietà, punti di prelievo, prodotti e finestre SmartFlex pubblicati dalle API ufficiali di Octopus Energy Italy.
- :busts_in_silhouette: **Gestione multi-account** – rilevamento automatico di tutti i conti collegati alle credenziali e suddivisione dei dati per ciascuno di essi.
- :money_with_wings: **Tariffe dettagliate per luce e gas** – esposizione del prodotto attivo, dei prezzi base/F2/F3, delle quote fisse, dell’unità di misura (incluso il prezzo gas in €/m³) e dei link ai termini contrattuali.
- :house_with_garden: **Monitoraggio POD e PDR** – stato fornitura, date di attivazione, presenza del contatore smart e motivazioni di eventuale cessazione.
- :battery: **Funzionalità SmartFlex** – stato dispositivi, limiti di carica, finestre di dispatch correnti/future e capacità della batteria del veicolo.
- :arrows_clockwise: **Aggiornamenti integrati in Home Assistant** – utilizzo del DataUpdateCoordinator, registrazione automatica delle entità e servizi dedicati per aggiornare le preferenze di ricarica.

## :gear: Prerequisiti

- Account cliente Octopus Energy Italy con accesso al portale clienti.
- Home Assistant 2023.12 o successivo (supporto config flow asincrone e `python-graphql-client`).
- Facoltativo: attivare il debug in `configuration.yaml` per indagare eventuali problemi API.

```yaml
logger:
  logs:
    custom_components.octopus_energy_it: debug
```

## :inbox_tray: Installazione

### :package: HACS (consigliata)

1. In HACS Cerca “Octopus Energy Italy” e installa l’integrazione.
3. Riavvia Home Assistant quando richiesto.
4. Configura l’integrazione da **Impostazioni → Dispositivi e servizi → Aggiungi integrazione**.

### :file_folder: Installazione manuale

1. Copia la cartella `custom_components/octopus_energy_it` nella directory `custom_components` della tua istanza Home Assistant.
2. Riavvia Home Assistant.
3. Segui la procedura guidata da **Impostazioni → Dispositivi e servizi → Aggiungi integrazione**.

## :wrench: Configurazione iniziale

1. Seleziona **Octopus Energy Italy** tra le integrazioni disponibili.
2. Inserisci e-mail e password utilizzate sul portale clienti Octopus Energy Italy.
3. La procedura convalida le credenziali, recupera i numeri di conto e li memorizza nella config entry.
4. Le entità vengono create dopo il primo aggiornamento del coordinatore (circa 60 secondi).

## :bar_chart: Modello dati gestito

- :ledger: **Accounts & Ledgers** – saldi per elettricità, gas, calore e altri ledger (es. canone TV).
- :houses: **Proprietà e punti di prelievo** – POD, PDR, stato di fornitura, date di enrolment, dati smart meter e motivazioni di cancellazione.
- :bookmark_tabs: **Prodotti** – prodotti attivi e storici con prezzi dettagliati, oneri, unità, tipologia tariffaria, termini contrattuali e periodo di validità.
- :robot: **Dispositivi & preferenze** – dispositivi SmartFlex, stato di sospensione, programmi di ricarica e target percentuale.
- :alarm_clock: **Dispatch SmartFlex** – finestre di carica pianificate e completate per automazioni di ricarica intelligente.

## :electric_plug: Entità esposte

### :bulb: Sensori binari

- `binary_sensor.octopus_<account>_intelligent_dispatching` – `on` se è attiva una finestra di dispatch.

### :satellite: Sensori

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
| `sensor.octopus_<account>_electricity_last_reading_date` | data | — |
| `sensor.octopus_<account>_gas_last_reading` | m³ | `recorded_at`, `measurement_type`, `measurement_source`, `unit_of_measurement` |
| `sensor.octopus_<account>_electricity_meter_status` | testo | `account_number`, `pod`, `supply_point_id`, `enrollment_status`, `enrollment_started_at`, `supply_started_at`, `is_smart_meter`, `cancellation_reason` |
| `sensor.octopus_<account>_gas_meter_status` | testo | `account_number`, `pdr`, `enrollment_status`, `enrollment_started_at`, `supply_started_at`, `is_smart_meter`, `cancellation_reason` |

**Saldi e contratti**

- `sensor.octopus_<account>_electricity_balance`, `sensor.octopus_<account>_gas_balance`, `sensor.octopus_<account>_heat_balance` e `sensor.octopus_<account>_<ledger>_balance` riportano i saldi monetari forniti dall’API.
- `sensor.octopus_<account>_electricity_contract_start`, `_electricity_contract_end` e `_electricity_contract_days_until_expiry` espongono rispettivamente data di attivazione, data di termine e giorni residui del contratto luce (equivalenti disponibili per il gas).
- `sensor.octopus_<account>_vehicle_battery_size` indica la capacità stimata dell’accumulatore e fornisce gli attributi `account_number`, `device_id`, `device_name`, `vehicle_model`, `device_provider`.

**SmartFlex e dispatch**

| Entità | Unità | Attributi extra |
| --- | --- | --- |
| `sensor.octopus_<account>_ev_charge_status` | testo | `account_number`, `device_id`, `device_name`, `device_model`, `device_provider`, `battery_capacity_kwh`, `status_current_state`, `status_connection_state`, `status_is_suspended`, `preferences_mode`, `preferences_unit`, `preferences_target_type`, `allow_grid_export`, `schedules`, `target_day_of_week`, `target_time`, `target_percentage`, `boost_active`, `boost_available`, `last_synced_at` |
| `sensor.octopus_<account>_ev_charge_target` | % | — |
| `sensor.octopus_<account>_ev_ready_time` | HH:MM | — |

> I sensori e i controlli dedicati a SmartFlex compaiono solo per i dispositivi Intelligent Octopus supportati; abilita dall'Entity Registry quelli necessari.

### :arrow_up_down: Number

- `number.octopus_<account>_<device_id>_charge_target` – imposta il target di ricarica SmartFlex (20–100%, passi da 5). L’aggiornamento viene propagato al coordinatore condiviso, che mantiene coerenti sensori e controlli.

### :alarm_clock: Select

- `select.octopus_<account>_<device_id>_target_time_select` – seleziona l'orario di completamento SmartFlex. Le opzioni sono generate in base ai limiti `timeFrom`/`timeTo` e allo `timeStep` restituiti dall'API.

### :control_knobs: Switch

- `switch.octopus_<account>_ev_charge_smart_control` – sospende o riattiva il controllo intelligente del dispositivo principale.
- `switch.octopus_<account>_<device_name>_boost_charge` – avvia o annulla il boost immediato quando disponibile (solo dispositivi compatibili).
### :gear: Servizi

- `octopus_energy_it.set_device_preferences`
  - `device_id`: ID del dispositivo (obbligatorio)
  - `target_percentage`: valore 20–100 con passi da 5 (obbligatorio)
  - `target_time`: orario di conclusione (`HH:MM`, 04:00–17:00) (obbligatorio)

## :toolbox: Risoluzione problemi

- Verifica **Strumenti per sviluppatori → Log** per messaggi di errore o avviso.
- Imposta `LOG_API_RESPONSES` o `LOG_TOKEN_RESPONSES` su `True` in `custom_components/octopus_energy_it/const.py` per log estesi (solo per debug temporaneo).
- Se non compaiono entità, assicurati che almeno un POD o PDR sia attivo nell’area clienti Octopus Energy.

---

Documentazione aggiornata in base alle API GraphQL di Octopus Energy Italy.
