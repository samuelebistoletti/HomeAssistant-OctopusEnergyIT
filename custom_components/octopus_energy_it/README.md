# Integrazione Octopus Energy Italia per Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
![installation_badge](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=utenti&suffix=%20installs&cacheSeconds=15600&url=https://analytics.home-assistant.io/custom_integrations.json&query=$.octopus_energy_it.total)

Questa integrazione personalizzata utilizza le API GraphQL Kraken di Octopus Energy Italia per portare in Home Assistant saldi, tariffe, punti di fornitura, dispositivi SmartFlex e preferenze di ricarica.

*Octopus Energy® è un marchio registrato del gruppo Octopus Energy. Il progetto è mantenuto dalla community e non è affiliato all’azienda.*

---

## Caratteristiche principali

- **Copertura completa dello schema italiano** – interrogazioni delle entità `account`, `ledgers`, `properties`, `supplyPoints`, `devices` e delle query Flex/dispatch pubblicate su `https://api.oeit-kraken.energy/v1/graphql/`.
- **Supporto multi-account** – rilevamento automatico di tutti i conti collegati alle credenziali e separazione dei dati per ciascuno di essi.
- **Tariffe con metadati arricchiti** – esposizione del prodotto attivo, prezzi base/F2/F3, oneri fissi, unità di misura, link ai termini di contratto e scadenze per elettricità e gas.
- **Monitoraggio POD/PDR** – stato di fornitura, data di enrolment, flag contatore smart, motivazioni di cancellazione e contratti associati a ogni punto.
- **SmartFlex avanzato** – pianificazione, finestre di dispatch correnti e future, stato dispositivi, target di ricarica preferiti e capacità batteria del veicolo.
- **Integrazione nativa con HA** – utilizzo dell’Entity Registry, aggiornamenti coordinati ogni minuto (`UPDATE_INTERVAL`) e servizi dedicati per configurare le preferenze di ricarica.

## Prerequisiti

- Account cliente Octopus Energy Italia con accesso al portale Kraken.
- Home Assistant 2023.12 o successivo (config flow asincrone e pacchetto `python_graphql_client`).
- Facoltativo: abilita il debug in `configuration.yaml` per analizzare eventuali problemi API.

```yaml
logger:
  logs:
    custom_components.octopus_energy_it: debug
```

## Installazione

### HACS (consigliata)

1. In HACS apri **Integrazioni → ⋮ → Custom repositories** e aggiungi `https://github.com/samuelebistoletti/octopus_energy_it` con tipo *Integration*.
2. Cerca “Octopus Energy Italy” e installa l’integrazione.
3. Riavvia Home Assistant quando richiesto.
4. Configura l’integrazione da **Impostazioni → Dispositivi e Servizi → Aggiungi integrazione**.

### Installazione manuale

1. Copia la cartella `custom_components/octopus_energy_it` nella directory `custom_components` della tua istanza HA.
2. Riavvia Home Assistant.
3. Segui la procedura guidata da **Impostazioni → Dispositivi e Servizi → Aggiungi integrazione**.

## Configurazione iniziale

1. Seleziona **Octopus Energy Italy** tra le integrazioni disponibili.
2. Inserisci e-mail e password usate sul portale Kraken italiano.
3. La procedura convalida le credenziali, recupera uno o più numeri di conto e li memorizza nella config entry.
4. Gli entity vengono creati dopo il primo aggiornamento del coordinatore (circa 60 secondi).

## Modello dati gestito

- **Accounts & Ledgers** – saldi per elettricità, gas, calore e altri ledger (es. canone TV).
- **Properties & Supply Points** – POD/PDR, stato e data di enrolment, stato fornitura, smart meter e motivazioni di cancellazione.
- **Products** – prodotti attivi e storici con prezzi dettagliati, oneri, unità, tipologia tariffaria, termini contrattuali e finestra di validità.
- **Devices & Preferences** – dispositivi SmartFlex, stato di sospensione, programmi di ricarica e target percentuale.
- **Dispatches** – finestre di carica pianificate e completate per l’automazione delle ricariche intelligenti.

## Entità esposte

### Sensori binari

- `binary_sensor.octopus_<account>_intelligent_dispatching` – `on` se una finestra di dispatch è attiva.

### Sensori

**Tariffe e prezzi**
- `sensor.octopus_<account>_electricity_price`
- `sensor.octopus_<account>_electricity_product`
- `sensor.octopus_<account>_electricity_standing_charge`
- `sensor.octopus_<account>_gas_tariff`
- `sensor.octopus_<account>_gas_product`
- `sensor.octopus_<account>_gas_price`
- `sensor.octopus_<account>_gas_standing_charge`

**Saldi ledger**
- `sensor.octopus_<account>_electricity_balance`
- `sensor.octopus_<account>_gas_balance`
- `sensor.octopus_<account>_heat_balance`
- `sensor.octopus_<account>_<ledger>_balance`

**Punti di fornitura**
- `sensor.octopus_<account>_electricity_supply_status`
- `sensor.octopus_<account>_gas_supply_status`
- `sensor.octopus_<account>_gas_pdr`
- `sensor.octopus_<account>_gas_supply_point_id`

**Contratti elettricità**
- `sensor.octopus_<account>_electricity_contract_start`
- `sensor.octopus_<account>_electricity_contract_end`
- `sensor.octopus_<account>_electricity_contract_days_until_expiry`

**Contratti gas**
- `sensor.octopus_<account>_gas_contract_start`
- `sensor.octopus_<account>_gas_contract_end`
- `sensor.octopus_<account>_gas_contract_days_until_expiry`

**Storico accordi**
- `sensor.octopus_<account>_electricity_agreements`
- `sensor.octopus_<account>_gas_agreements`

**Finestre SmartFlex**
- `sensor.octopus_<account>_dispatch_current_start`
- `sensor.octopus_<account>_dispatch_current_end`
- `sensor.octopus_<account>_dispatch_next_start`
- `sensor.octopus_<account>_dispatch_next_end`

**Dispositivi e veicoli**
- `sensor.octopus_<account>_device_status`
- `sensor.octopus_<account>_device_charge_target`
- `sensor.octopus_<account>_device_target_time`
- `sensor.octopus_<account>_vehicle_battery_size`

**Controlli**
- `number.octopus_<account>_<device>_charge_target` – slider per impostare la percentuale di carica SmartFlex
- `select.octopus_<account>_<device>_target_time_select` – menu per scegliere l’orario di completamento

> I sensori e i controlli dedicati a SmartFlex (finestre, target, orario, informazioni prodotto e batteria veicolo) sono creati disattivati: abilita solo quelli necessari dall’Entity Registry.

### Switch

- `switch.octopus_<account>_device_smart_control` – sospende/riattiva il controllo intelligente del dispositivo principale.
- `switch.octopus_<account>_<device_name>_boost_charge` – attiva la ricarica immediata (solo dispositivi compatibili con il boost).

### Servizi

- `octopus_energy_it.set_device_preferences`
  - `device_id`: ID del dispositivo (obbligatorio)
  - `target_percentage`: valore 20–100 con passi da 5 (obbligatorio)
  - `target_time`: orario di conclusione (`HH:MM`, 04:00–17:00) (obbligatorio)

## Troubleshooting

- Verifica **Strumenti per sviluppatori → Log** per messaggi di errore o avviso.
- Imposta `LOG_API_RESPONSES` o `LOG_TOKEN_RESPONSES` su `True` in `custom_components/octopus_energy_it/const.py` per log estesi (solo per debug temporaneo).
- Se non compaiono entità, assicurati che almeno un POD o PDR sia attivo nel portale Kraken.

---

Documentazione aggiornata in base alle API GraphQL di Octopus Energy Italia.
