"""Validate every GraphQL operation of the API client against the Kraken schema.

The schema fixture is refreshed with ``scripts/update-graphql-schema``. These
tests fail when a query stops being valid (a field was removed or renamed) or
starts using a deprecated field, so API changes surface in CI before they
break users.
"""

import ast
import json
from pathlib import Path
import re

from graphql import (
    GraphQLSchema,
    TypeInfo,
    TypeInfoVisitor,
    Visitor,
    build_client_schema,
    parse,
    validate,
    visit,
)
import pytest

_ROOT = Path(__file__).resolve().parent.parent
_CLIENT = _ROOT / "custom_components" / "octopus_energy_it" / "octopus_energy_it.py"
_SCHEMA = _ROOT / "tests" / "fixtures" / "oeit_graphql_schema.json"

# Deprecated fields still in use on purpose, with the planned removal date.
# Remove an entry as soon as the code stops using the field.
_ALLOWED_DEPRECATED = {
    # SmartFlex `provider`: replace with `capabilities` (removal >= 2027-04-15).
    "provider",
}


def _operations() -> dict[str, str]:
    """Return {name: document} for every GraphQL string in the client module."""
    tree = ast.parse(_CLIENT.read_text(encoding="utf-8"))
    operations: dict[str, str] = {}
    for node in tree.body:  # module-level constants
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            value = node.value.value
            if isinstance(value, str) and re.match(r"\s*(query|mutation)\b", value):
                operations[node.targets[0].id] = value
    return operations


@pytest.fixture(scope="module")
def schema() -> GraphQLSchema:
    return build_client_schema(json.loads(_SCHEMA.read_text(encoding="utf-8"))["data"])


_OPERATIONS = _operations()


def test_client_operations_were_found():
    assert {
        "COMPREHENSIVE_QUERY",
        "FLEX_PLANNED_DISPATCHES_QUERY",
        "LOGIN_MUTATION",
    } <= set(_OPERATIONS)


@pytest.mark.parametrize("name", sorted(set(_OPERATIONS) - {"LOGIN_MUTATION"}))
def test_operation_is_valid(schema, name):
    errors = validate(schema, parse(_OPERATIONS[name]))
    assert not errors, [error.message for error in errors]


def test_login_mutation_only_fails_on_hidden_credential_fields(schema):
    # Kraken hides `email`/`password` of ObtainJSONWebTokenInput from
    # introspection, although the API accepts them; anything else must be valid.
    errors = validate(schema, parse(_OPERATIONS["LOGIN_MUTATION"]))
    unexpected = [
        e.message
        for e in errors
        if "ObtainJSONWebTokenInput" not in e.message
        or not re.search(r"unknown field '(email|password)'", e.message)
    ]
    assert not unexpected


@pytest.mark.parametrize("name", sorted(_OPERATIONS))
def test_operation_uses_no_deprecated_fields(schema, name):
    type_info = TypeInfo(schema)
    deprecated: list[str] = []

    class _Collector(Visitor):
        def enter_field(self, node, *_args):
            field = type_info.get_field_def()
            if field is not None and field.deprecation_reason:
                deprecated.append(node.name.value)

    visit(parse(_OPERATIONS[name]), TypeInfoVisitor(type_info, _Collector()))
    assert set(deprecated) <= _ALLOWED_DEPRECATED, deprecated
