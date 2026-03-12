# Contributing Guidelines

Contributing to this project should be as easy and transparent as possible, whether it involves:

- Reporting a bug
- Discussing the current state of the code
- Submitting a fix
- Proposing new features

## GitHub is Used for Everything

GitHub is used to host the code, track issues and feature requests, and accept pull requests.

Pull requests are the best way to propose changes to the codebase.

1. Fork the repository and create your branch from `main`.
2. If you have changed anything, update the documentation accordingly.
3. Make sure the code passes the linter (`bash scripts/lint`).
4. Make sure all tests pass (`python -m pytest tests/`).
5. Open the pull request!

## All Contributions are Under the MIT License

In short, when you submit code changes, your contributions are understood to be under the same [MIT License](http://choosealicense.com/licenses/mit/) that covers the project. Contact the maintainers if this is a concern.

## Reporting Bugs Using [GitHub Issues](../../issues)

GitHub Issues are used to track public bugs.
Report a bug by [opening a new issue](../../issues/new/choose).

**Good bug reports** tend to include:

- A brief summary and/or background
- Steps to reproduce the problem (be as specific as possible)
- What you expected to happen
- What actually happens
- Notes (including why you think this might be happening, or things you have already tried)

## Code Style

The project uses [ruff](https://github.com/astral-sh/ruff) for formatting and linting.

```bash
# Format and auto-fix (ruff format + ruff check --fix)
bash scripts/lint
```

Do not use `black`, `flake8`, or `pylint` directly — `ruff` replaces them all.

## Testing Changes

### Automated Tests

The test suite uses `pytest` and `pytest-asyncio`. All Home Assistant dependencies are stubbed, so no HA installation is required.

```bash
# Install test dependencies
pip install -r requirements_test.txt

# Run all tests
python -m pytest tests/

# Verbose output
python -m pytest tests/ -v

# Single module
python -m pytest tests/test_api_client.py -v
```

Tests cover the API client, sensors, switches, binary sensors, and coordinator. Add or update tests whenever you modify the logic of these components.

### Local Development Environment (Home Assistant)

To manually test the integration against a local Home Assistant instance:

```bash
# Install dev dependencies
bash scripts/setup

# Start Home Assistant at http://localhost:8123
docker-compose up

# Follow logs
docker-compose logs -f homeassistant
```

The dev configuration is in `config/configuration.yaml`.

## License

By contributing, you agree that your contributions will be licensed under the project's MIT License.
