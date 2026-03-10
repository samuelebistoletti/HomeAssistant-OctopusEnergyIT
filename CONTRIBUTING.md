# Linee guida per contribuire

Contribuire a questo progetto deve essere il più semplice e trasparente possibile, che si tratti di:

- Segnalare un bug
- Discutere lo stato attuale del codice
- Inviare una correzione
- Proporre nuove funzionalità

## GitHub è usato per tutto

GitHub è usato per ospitare il codice, tracciare issue e richieste di funzionalità e accettare pull request.

Le pull request sono il modo migliore per proporre modifiche al codebase.

1. Fai un fork del repository e crea il tuo branch da `main`.
2. Se hai cambiato qualcosa, aggiorna la documentazione di conseguenza.
3. Assicurati che il codice passi il linter (`bash scripts/lint`).
4. Assicurati che tutti i test passino (`python -m pytest tests/`).
5. Apri la pull request!

## Tutte le contribuzioni sono sotto la licenza MIT

In breve, quando invii modifiche al codice, le tue contribuzioni si intendono sotto la stessa [licenza MIT](http://choosealicense.com/licenses/mit/) che copre il progetto. Contatta i maintainer se questo è un problema.

## Segnalare bug usando le [issue](../../issues) di GitHub

Le issue GitHub vengono usate per tracciare i bug pubblici.
Segnala un bug [aprendo una nuova issue](../../issues/new/choose).

**Le buone segnalazioni di bug** tendono ad avere:

- Un breve riepilogo e/o contesto
- Passaggi per riprodurre il problema (il più specifici possibile)
- Cosa ti aspettavi che accadesse
- Cosa accade invece
- Note (incluso eventualmente perché pensi che stia succedendo o cosa hai già provato)

## Stile del codice

Il progetto usa [ruff](https://github.com/astral-sh/ruff) per la formattazione e il linting.

```bash
# Formatta e corregge automaticamente
bash scripts/lint
```

Non usare `black`, `flake8` o `pylint` direttamente: `ruff` li sostituisce tutti.

## Testare le modifiche

### Test automatici

La suite di test usa `pytest` e `pytest-asyncio`. Tutte le dipendenze di Home Assistant vengono simulate tramite stub, quindi non è necessaria alcuna installazione di HA.

```bash
# Installa le dipendenze di test
pip install -r requirements_test.txt

# Esegui tutti i test
python -m pytest tests/

# Con output verboso
python -m pytest tests/ -v

# Solo un modulo
python -m pytest tests/test_api_client.py -v
```

I test coprono il client API, i sensori, gli switch, i binary sensor e il coordinator. Aggiungi o aggiorna i test quando modifichi la logica di questi componenti.

### Ambiente di sviluppo locale (Home Assistant)

Per testare manualmente l'integrazione in un'istanza Home Assistant locale:

```bash
# Installa dipendenze di sviluppo
bash scripts/setup

# Avvia Home Assistant su http://localhost:8123
docker-compose up

# Segui i log
docker-compose logs -f homeassistant
```

La configurazione di sviluppo è in `config/configuration.yaml`.

## Licenza

Contribuendo, accetti che le tue contribuzioni saranno licenziate sotto la licenza MIT del progetto.
