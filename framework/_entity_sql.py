"""Render conservative SQL from explicitly documented entity mappings."""

from __future__ import annotations

import re
from typing import Any

if __package__:
    from framework._contract_common import (
        SQL_IDENTIFIER, _normalized_name, _quote_identifier,
    )
    from framework._entity_mapping import (
        _entity_relationships, _source_physical_table,
    )

else:
    from _contract_common import SQL_IDENTIFIER, _normalized_name, _quote_identifier
    from _entity_mapping import _entity_relationships, _source_physical_table


def _render_join_predicate(predicate: Any, aliases: set[str]) -> str | None:
    if not isinstance(predicate, str) or not predicate.strip():
        return None
    comparisons = re.split(r"\s+AND\s+", predicate.strip(), flags=re.IGNORECASE)
    pattern = re.compile(
        r"\s*(?P<left_alias>[A-Za-z_][A-Za-z0-9_]*)\s*\.\s*"
        r"\[?(?P<left_column>[A-Za-z_][A-Za-z0-9_]*)\]?\s*"
        r"(?P<operator>=|<>|!=|<=|>=|<|>)\s*"
        r"(?P<right_alias>[A-Za-z_][A-Za-z0-9_]*)\s*\.\s*"
        r"\[?(?P<right_column>[A-Za-z_][A-Za-z0-9_]*)\]?\s*"
    )
    rendered = []
    for comparison in comparisons:
        match = pattern.fullmatch(comparison)
        if not match:
            return None
        left_alias = match.group("left_alias")
        right_alias = match.group("right_alias")
        if left_alias not in aliases or right_alias not in aliases:
            return None
        rendered.append(
            f"{_quote_identifier(left_alias)}.{_quote_identifier(match.group('left_column'))} "
            f"{match.group('operator')} "
            f"{_quote_identifier(right_alias)}.{_quote_identifier(match.group('right_column'))}"
        )
    return " AND ".join(rendered)

def _governance_expression(
    field_name: str,
    governance_rows: list[dict[str, Any]],
    aliases: set[str],
) -> str | None:
    normalized_field = _normalized_name(field_name)
    for row in governance_rows:
        if _normalized_name(row.get("Target Field")) != normalized_field:
            continue
        expression = row.get("Rule Logic / Expression")
        if not isinstance(expression, str):
            continue
        match = re.fullmatch(
            r"\s*COALESCE\(\s*([A-Za-z_][A-Za-z0-9_]*)\.\[?"
            r"([A-Za-z_][A-Za-z0-9_]*)\]?\s*,\s*(-?\d+(?:\.\d+)?)\s*\)\s*",
            expression,
            flags=re.IGNORECASE,
        )
        if match and match.group(1) in aliases:
            return (
                f"COALESCE({_quote_identifier(match.group(1))}."
                f"{_quote_identifier(match.group(2))}, {match.group(3)})"
            )
    return None

def _build_entity_sql(
    entity: dict[str, Any],
    attributes: list[dict[str, Any]],
    definition: dict[str, Any] | None = None,
    relationship_rows: list[dict[str, Any]] | None = None,
    ingestion_rows: list[dict[str, Any]] | None = None,
    governance_rows: list[dict[str, Any]] | None = None,
) -> tuple[str, bool, list[str]]:
    name = entity["metadata"]["name"]
    entity_type = entity["metadata"].get("entityType")
    definition = definition or {}
    relationship_rows = relationship_rows or []
    ingestion_rows = ingestion_rows or []
    governance_rows = governance_rows or []
    reasons = []
    source_references: set[tuple[str, str, str]] = set()
    physical_by_source: dict[str, tuple[str, str]] = {}
    projections = []

    if entity_type not in {"dimension", "fact"}:
        reasons.append("worksheet name does not identify a fact or dimension")
    if not attributes:
        reasons.append("no target fields are documented")

    field_names: set[str] = set()
    for attribute in attributes:
        field_name = attribute["name"]
        mapping = attribute["sourceMapping"]
        if field_name.casefold() in field_names:
            reasons.append(f"duplicate target field {field_name!r}")
        field_names.add(field_name.casefold())
        if not SQL_IDENTIFIER.fullmatch(field_name):
            reasons.append(f"target field {field_name!r} is not a simple SQL identifier")
        if mapping is None:
            reasons.append(f"target field {field_name!r} has no complete source mapping")
            continue
        source_references.add((
            mapping["sourceSystem"],
            mapping["sourceSchema"],
            mapping["sourceTable"],
        ))
        physical_by_source[mapping["source"]] = _source_physical_table(
            mapping,
            ingestion_rows,
        )
        source_field = mapping["fields"]
        if not SQL_IDENTIFIER.fullmatch(source_field):
            reasons.append(
                f"source mapping for {field_name!r} is not a single SQL identifier"
            )
            continue
    entity_relationships = _entity_relationships(
        entity,
        attributes,
        relationship_rows,
        ingestion_rows,
    )
    table_aliases: dict[tuple[str, str], list[str]] = {}
    aliases: set[str] = set()
    for relationship in entity_relationships:
        for side in ("source", "target"):
            reference = relationship[side]
            table_key = (
                _normalized_name(reference["schema"]),
                _normalized_name(reference["table"]),
            )
            table_aliases.setdefault(table_key, []).append(reference["alias"])
            aliases.add(reference["alias"])

    rendered_joins = []
    root_reference = None
    for relationship in entity_relationships:
        source_ref = relationship["source"]
        target_ref = relationship["target"]
        if root_reference is None:
            root_reference = source_ref
        join_type = str(relationship["joinType"] or "").strip().upper()
        if join_type not in {
            "INNER JOIN", "LEFT JOIN", "LEFT OUTER JOIN", "RIGHT JOIN",
            "FULL JOIN", "FULL OUTER JOIN",
        }:
            reasons.append(f"unsupported documented join type {join_type!r}")
            continue
        predicate = _render_join_predicate(relationship["predicate"], aliases)
        if predicate is None:
            reasons.append("a documented join predicate is incomplete or unsupported")
            continue
        rendered_joins.append(
            f"{join_type} {_quote_identifier(target_ref['schema'])}."
            f"{_quote_identifier(target_ref['table'])} AS "
            f"{_quote_identifier(target_ref['alias'])}\n    ON {predicate}"
        )

    required_physical_tables = {
        (_normalized_name(schema), _normalized_name(table))
        for schema, table in physical_by_source.values()
    }
    represented_tables = set(table_aliases)
    if len(required_physical_tables) > 1:
        if not entity_relationships or required_physical_tables - represented_tables:
            reasons.append("documented relationships do not connect every mapped source table")

    for attribute in attributes:
        mapping = attribute["sourceMapping"]
        if mapping is None:
            continue
        physical = physical_by_source[mapping["source"]]
        physical_key = tuple(_normalized_name(value) for value in physical)
        matching_aliases = list(dict.fromkeys(table_aliases.get(physical_key, [])))
        alias = None
        target_phrase = _normalized_name(attribute["name"])

        if len(matching_aliases) > 1:
            for relationship in entity_relationships:
                target_ref = relationship["target"]
                target_key = (
                    _normalized_name(target_ref["schema"]),
                    _normalized_name(target_ref["table"]),
                )
                description = _normalized_name(relationship.get("description"))
                if (
                    target_key == physical_key
                    and len(target_phrase) >= 10
                    and target_phrase in description
                ):
                    alias = target_ref["alias"]
                    break
            if alias is None:
                alias = next((
                    relationship["source"]["alias"]
                    for relationship in entity_relationships
                    if (
                        _normalized_name(relationship["source"]["schema"]),
                        _normalized_name(relationship["source"]["table"]),
                    ) == physical_key
                ), None)
            if alias is None:
                reasons.append(f"source alias for target field {attribute['name']!r} is ambiguous")
                continue
        elif matching_aliases:
            alias = matching_aliases[0]

        projection = _governance_expression(
            attribute["name"],
            governance_rows,
            aliases,
        )
        if projection is None:
            if attribute["calculation"] or attribute["transformation"]:
                reasons.append(f"target field {attribute['name']!r} has an explicit transformation")
                continue
            if not SQL_IDENTIFIER.fullmatch(mapping["fields"]):
                continue
            source_column = _quote_identifier(mapping["fields"])
            projection = f"{_quote_identifier(alias)}.{source_column}" if alias else source_column
        projections.append(
            f"    {projection} AS {_quote_identifier(attribute['name'])}"
        )

    if not source_references:
        reasons.append("entity has no documented source table mappings")
    elif len(source_references) > 1 and not entity_relationships:
        reasons.append("entity uses multiple source tables without documented joins")

    unique_reasons = list(dict.fromkeys(reasons))
    if root_reference is None and len(required_physical_tables) == 1:
        schema, table = next(iter(physical_by_source.values()))
        root_reference = {"schema": schema, "table": table, "alias": ""}

    if root_reference is None or not projections:
        comments = [
            f"-- DRAFT ONLY: SQL for {name} is not executable yet.",
            "-- Resolve the following source mappings, joins, or field rules:",
            *(f"-- TODO: {reason}" for reason in unique_reasons),
        ]
        return "\n".join(comments) + "\n", False, unique_reasons

    target_schema = str(definition.get("Target Schema") or "gold")
    target_table = str(definition.get("Target Table") or name)
    from_clause = (
        f"FROM {_quote_identifier(root_reference['schema'])}."
        f"{_quote_identifier(root_reference['table'])}"
    )
    if root_reference.get("alias"):
        from_clause += f" AS {_quote_identifier(root_reference['alias'])}"
    if rendered_joins:
        from_clause += "\n" + "\n".join(rendered_joins)

    if unique_reasons:
        comments = [
            f"-- DRAFT ONLY: SQL for {name} is incomplete and must not be deployed.",
            "-- Documented source joins are included; unresolved fields are listed below.",
            *(f"-- TODO: {reason}" for reason in unique_reasons),
        ]
        sql = (
            "\n".join(comments)
            + "\nSELECT\n"
            + ",\n".join(projections)
            + "\n"
            + from_clause
            + ";\n"
        )
        return sql, False, unique_reasons

    sql = (
        f"-- Generated from {entity['metadata']['sourceWorksheet']} and documented S2T relationships.\n"
        f"CREATE OR ALTER VIEW {_quote_identifier(target_schema)}."
        f"{_quote_identifier(target_table)} AS\n"
        "SELECT\n"
        + ",\n".join(projections)
        + "\n"
        + from_clause
        + ";\n"
    )
    return sql, True, []
