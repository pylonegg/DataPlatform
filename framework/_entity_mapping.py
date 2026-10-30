"""Translate entity rows and workbook relationships into contract data."""

from __future__ import annotations

import re
from typing import Any

if __package__:
    from framework._contract_common import _normalized_name, _source_id

else:
    from _contract_common import _normalized_name, _source_id


def _documented_flag(value: Any) -> bool | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().casefold()
    if normalized in {"y", "yes", "true", "1"}:
        return True
    if normalized in {"n", "no", "false", "0"}:
        return False
    return None

def _entity_attributes(entity: dict[str, Any]) -> list[dict[str, Any]]:
    attributes = []
    for row in entity["spec"].get("records", []):
        field_name = row.get("Field")
        if not isinstance(field_name, str) or not field_name.strip():
            continue

        source_system = row.get("Source System")
        source_schema = row.get("Source Schema")
        source_table = row.get("Source Table")
        source_fields = row.get("Source Field(s)")
        source_mapping = None
        if all(isinstance(value, str) and value.strip() for value in (
            source_system,
            source_schema,
            source_table,
            source_fields,
        )):
            source_mapping = {
                "source": _source_id(source_system, source_schema, source_table),
                "sourceSystem": source_system,
                "sourceSchema": source_schema,
                "sourceTable": source_table,
                "fields": source_fields.strip(),
            }

        mandatory = _documented_flag(row.get("Is Mandatory"))
        attributes.append({
            "name": field_name.strip(),
            "attributeType": row.get("Attribute Type"),
            "dataType": row.get("Field Type"),
            "size": row.get("Field Size"),
            "nullable": None if mandatory is None else not mandatory,
            "keys": {
                "primary": _documented_flag(row.get("Is Primary Key")),
                "business": _documented_flag(row.get("Is business Key")),
                "alternate": _documented_flag(row.get("Is Alternate Key")),
            },
            "measureDimensionType": row.get("Measure / Dimension Type"),
            "format": row.get("Format String"),
            "validations": row.get("Validations"),
            "calculation": row.get("Calculation(s)"),
            "calculationType": row.get("Calculation Type"),
            "transformation": row.get("Transformations, including lookup entity"),
            "notes": row.get("Notes"),
            "sourceMapping": source_mapping,
            "provenance": {
                "worksheet": entity["metadata"]["sourceWorksheet"],
                "excelRow": row.get("_excel_row"),
            },
        })
    return attributes

def _table_alias(value: Any) -> dict[str, str] | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"\s*\[(?P<schema>[^\]]+)\]\s*\.\s*"
        r"(?:\[(?P<bracket_table>[^\]]+)\]|(?P<table>[^\s()]+))"
        r"\s*(?:\((?P<alias>[^)]+)\))?\s*",
        value,
    )
    if not match:
        return None
    table = match.group("bracket_table") or match.group("table")
    return {
        "schema": match.group("schema"),
        "table": table,
        "alias": (match.group("alias") or table).strip().strip("[]"),
    }

def _source_physical_table(
    mapping: dict[str, Any],
    ingestion_rows: list[dict[str, Any]],
) -> tuple[str, str]:
    expected_table = _normalized_name(
        f"{mapping['sourceSchema']}_{mapping['sourceTable']}"
    )
    matches = [
        row
        for row in ingestion_rows
        if str(row.get("Source System", "")).casefold() == mapping["sourceSystem"].casefold()
        and _normalized_name(row.get("Source Table")) == expected_table
    ]
    if len(matches) == 1:
        return (
            str(matches[0].get("Source Schema") or mapping["sourceSchema"]),
            str(matches[0].get("Source Table") or mapping["sourceTable"]),
        )
    return mapping["sourceSchema"], mapping["sourceTable"]

def _entity_relationships(
    entity: dict[str, Any],
    attributes: list[dict[str, Any]],
    relationship_rows: list[dict[str, Any]],
    ingestion_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    physical_tables = set()
    for attribute in attributes:
        mapping = attribute["sourceMapping"]
        if mapping is not None:
            physical_tables.add(tuple(
                _normalized_name(value)
                for value in _source_physical_table(mapping, ingestion_rows)
            ))

    entity_name = _normalized_name(entity["metadata"]["name"])
    selected = []
    for row in relationship_rows:
        source_ref = _table_alias(row.get("Source Entity / Alias"))
        target_ref = _table_alias(row.get("Target / Lookup Entity Alias"))
        if source_ref is None or target_ref is None:
            continue
        source_table = (
            _normalized_name(source_ref["schema"]),
            _normalized_name(source_ref["table"]),
        )
        target_table = (
            _normalized_name(target_ref["schema"]),
            _normalized_name(target_ref["table"]),
        )
        matches_mapped_tables = (
            source_table in physical_tables and target_table in physical_tables
        )
        matches_entity_root = (
            not physical_tables
            and _normalized_name(source_ref["table"]) == entity_name
        )
        if matches_mapped_tables or matches_entity_root:
            selected.append({
                "source": source_ref,
                "target": target_ref,
                "joinType": row.get("Join Type"),
                "predicate": row.get("Complete Join Predicate"),
                "cardinality": row.get("Cardinality Expectation"),
                "unmatchedHandling": row.get("Unmatched Row / Null Handling"),
                "description": row.get("Business Purpose / Description"),
                "provenance": {
                    "worksheet": "entity_relationships",
                    "excelRow": row.get("_excel_row"),
                },
            })
    return selected
