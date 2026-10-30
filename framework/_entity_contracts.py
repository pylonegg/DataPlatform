"""Assemble complete entity contract documents from mapping metadata."""

from __future__ import annotations

from typing import Any

if __package__:
    from framework._contract_common import (
        API_VERSION, ENTITY_CONTRACT_KIND, _enrichment_rows,
        _normalized_name, _optional_value,
    )
    from framework._entity_mapping import (
        _documented_flag, _entity_attributes, _entity_relationships,
    )
    from framework._entity_sql import _build_entity_sql

else:
    from _contract_common import (
        API_VERSION, ENTITY_CONTRACT_KIND, _enrichment_rows,
        _normalized_name, _optional_value,
    )
    from _entity_mapping import (
        _documented_flag, _entity_attributes, _entity_relationships,
    )
    from _entity_sql import _build_entity_sql


def _entity_contract(
    entity: dict[str, Any],
    metadata_file: str,
    sql_file: str,
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], str, list[str]]:
    attributes = _entity_attributes(entity)
    entity_name = entity["metadata"]["name"]
    definitions = _enrichment_rows(manifest, "entity_definitions")
    definition = next((
        row for row in definitions
        if str(row.get("Target Entity Name", "")).casefold() == entity_name.casefold()
    ), {})
    relationships = _entity_relationships(
        entity,
        attributes,
        _enrichment_rows(manifest, "entity_relationships"),
        _enrichment_rows(manifest, "source_ingestion"),
    )
    all_governance = _enrichment_rows(manifest, "governance")
    governance = [
        row
        for row in all_governance
        if str(row.get("Target Entity", "")).casefold()
        in {entity_name.casefold(), "all entities"}
    ]
    traceability = next((
        row for row in _enrichment_rows(manifest, "traceability")
        if str(row.get("Entity / Module", "")).casefold() == entity_name.casefold()
    ), None)

    blank_flags_false = any(
        "blank mandatory/key flags explicitly evaluate to false"
        in str(row.get("Rule Logic / Expression", "")).casefold()
        for row in all_governance
    )
    if blank_flags_false:
        for attribute in attributes:
            for key_name in ("primary", "business", "alternate"):
                if attribute["keys"][key_name] is None:
                    attribute["keys"][key_name] = False
            if attribute["nullable"] is None:
                attribute["nullable"] = True

    ingestion_rows = _enrichment_rows(manifest, "source_ingestion")
    entity_sql, sql_ready, unresolved = _build_entity_sql(
        entity,
        attributes,
        definition,
        _enrichment_rows(manifest, "entity_relationships"),
        ingestion_rows,
        governance,
    )
    source_dependencies = sorted({
        attribute["sourceMapping"]["source"]
        for attribute in attributes
        if attribute["sourceMapping"] is not None
    })
    definitions_by_table = {
        _normalized_name(row.get("Target Table")): str(row.get("Target Entity Name"))
        for row in definitions
        if row.get("Target Table") and row.get("Target Entity Name")
    }
    entity_dependencies = sorted({
        definitions_by_table[_normalized_name(relationship["target"]["table"])]
        for relationship in relationships
        if _normalized_name(relationship["target"]["table"]) in definitions_by_table
    })
    unresolved_contract = list(unresolved)
    if not definition:
        unresolved_contract.append("entity definition worksheet row is missing")
    if not definition.get("Business Purpose"):
        unresolved_contract.append("business purpose is not documented")
    if not definition.get("Business Key / Grain"):
        unresolved_contract.append("business key or grain is not documented")

    contract = {
        "apiVersion": API_VERSION,
        "kind": ENTITY_CONTRACT_KIND,
        "metadata": {
            "name": entity_name,
            "entityType": entity["metadata"].get("entityType"),
            "status": "draft",
            "owner": _optional_value(definition.get("Entity Owner")),
            "reviewStatus": _optional_value(traceability.get("Review Status")) if traceability else None,
            "sourceWorksheet": entity["metadata"]["sourceWorksheet"],
            "sourceWorkbook": entity["metadata"]["sourceWorkbook"],
            "mappingMetadata": metadata_file,
        },
        "spec": {
            "purpose": _optional_value(definition.get("Business Purpose")),
            "grain": _optional_value(definition.get("Business Key / Grain")),
            "target": {
                "schema": _optional_value(definition.get("Target Schema")),
                "table": _optional_value(definition.get("Target Table")),
                "layer": _optional_value(definition.get("Target Layer")),
            },
            "scdRules": {
                "type": _optional_value(definition.get("SCD Type & Rules")),
                "effectiveDateAndCurrentRow": _optional_value(
                    definition.get("Effective Date / Current Row Flag")
                ),
            },
            "attributes": attributes,
            "dependsOn": source_dependencies,
            "entityDependencies": entity_dependencies,
            "relationships": relationships,
            "qualityRules": governance,
            "load": {
                "strategy": _optional_value(definition.get("Load Strategy")),
                "orderConstraint": _optional_value(definition.get("Load Order Constraint")),
            },
            "traceability": {
                key: _optional_value(value)
                for key, value in (traceability or {}).items()
                if key != "_excel_row" and _optional_value(value) is not None
            },
            "execution": {
                "targetSchema": (
                    _optional_value(definition.get("Target Schema"))
                    or ("gold" if entity["metadata"].get("entityType") in {"dimension", "fact"} else None)
                ),
                "targetTable": _optional_value(definition.get("Target Table")) or entity_name,
                "sqlFile": sql_file,
                "sqlReady": sql_ready,
            },
            "unresolved": [
                *unresolved_contract,
            ],
        },
    }
    return contract, entity_sql, unresolved
