"""Build source contract documents and extraction queries."""

from __future__ import annotations

import os
import re
from typing import Any

if __package__:
    from framework._contract_common import (
        API_VERSION, SOURCE_CONTRACT_KIND, _optional_value,
        _quote_identifier, _source_id,
    )
    from framework._source_discovery import _source_column_mappings

else:
    from _contract_common import (
        API_VERSION, SOURCE_CONTRACT_KIND, _optional_value,
        _quote_identifier, _source_id,
    )
    from _source_discovery import _source_column_mappings


def _source_sql(
    source: dict[str, Any],
    columns: list[dict[str, Any]],
    ingestion_configuration: dict[str, Any] | None,
) -> tuple[str, bool, list[str]]:
    metadata = source["metadata"]
    override = _optional_value(
        ingestion_configuration.get("Extraction Filter / SQL Override")
        if ingestion_configuration
        else None
    )
    if isinstance(override, str):
        statement = override.strip()
        single_statement = statement.count(";") <= 1
        valid_start = statement.casefold().startswith(("select ", "with "))
        if not statement.endswith(";"):
            statement += ";"
        return (
            f"-- Explicit extraction SQL from source_ingestion worksheet.\n"
            f"{statement}\n",
            single_statement and valid_start,
            [] if single_statement and valid_start else [
                "documented SQL override must be a single SELECT or WITH statement"
            ],
        )

    eligible_columns = [column for column in columns if column["queryEligible"]]
    warnings = [
        f"Source field {column['name']!r} is not a simple SQL identifier and was omitted from the query."
        for column in columns
        if not column["queryEligible"]
    ]
    source_name = _source_id(
        metadata["sourceSystem"],
        metadata["sourceSchema"],
        metadata["sourceTable"],
    )
    if not eligible_columns:
        return (
            f"-- DRAFT ONLY: no simple source column identifiers were available for {source_name}.\n"
            "-- Add or confirm source field names before using this query.\n",
            False,
            warnings or ["No documented source fields are available."],
        )

    selected_fields = ",\n".join(
        f"    {_quote_identifier(column['name'])}"
        for column in eligible_columns
    )
    statement = (
        f"-- Source extraction query for {source_name}.\n"
        "-- Generated from explicitly documented source fields.\n"
        "SELECT\n"
        f"{selected_fields}\n"
        f"FROM {_quote_identifier(metadata['sourceSchema'])}."
        f"{_quote_identifier(metadata['sourceTable'])};\n"
    )
    return statement, not warnings, warnings

def _source_contract(
    source: dict[str, Any],
    source_metadata_file: str,
    sql_file: str,
    source_configuration: dict[str, Any] | None,
    ingestion_configuration: dict[str, Any] | None,
    discovered_columns: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], str, list[str]]:
    metadata = source["metadata"]
    columns = _source_column_mappings(source)
    query, query_ready, warnings = _source_sql(
        source,
        columns,
        ingestion_configuration,
    )
    discovered_columns = discovered_columns or []
    discovered_by_name = {
        str(column.get("name", "")).casefold(): column
        for column in discovered_columns
    }
    missing_mapped_columns = []
    for column in columns:
        discovered = discovered_by_name.get(column["name"].casefold())
        if discovered is None:
            missing_mapped_columns.append(column["name"])
            continue
        column.update({
            "dataType": discovered.get("dataType"),
            "sourceDataType": discovered.get("sourceDataType"),
            "nullable": discovered.get("nullable"),
            "maxLength": discovered.get("maxLength"),
            "precision": discovered.get("precision"),
            "scale": discovered.get("scale"),
            "primaryKey": discovered.get("primaryKey"),
        })
    if discovered_columns and missing_mapped_columns:
        query_ready = False
        warnings.append(
            "mapped source columns were not found in discovery: "
            + ", ".join(sorted(missing_mapped_columns))
        )

    documented_column_count = _optional_value(
        ingestion_configuration.get("Discovered Columns Count")
        if ingestion_configuration
        else None
    )
    count_mismatch = (
        isinstance(documented_column_count, (int, float))
        and discovered_columns
        and int(documented_column_count) != len(discovered_columns)
    )
    if count_mismatch:
        query_ready = False
        warnings.append(
            f"documented discovered column count {int(documented_column_count)} "
            f"does not match live count {len(discovered_columns)}"
        )
    source_id = _source_id(
        metadata["sourceSystem"],
        metadata["sourceSchema"],
        metadata["sourceTable"],
    )
    if source_configuration is None:
        warnings.append("source_system configuration is missing")
    if ingestion_configuration is None:
        warnings.append("source_ingestion configuration is missing")

    ingestion_mode = _optional_value(
        ingestion_configuration.get("Ingestion Mode")
        if ingestion_configuration
        else None
    )
    watermark = _optional_value(
        ingestion_configuration.get("Watermark Column")
        if ingestion_configuration
        else None
    )
    if isinstance(ingestion_mode, str) and ingestion_mode.casefold() == "incremental" and not watermark:
        warnings.append("incremental ingestion requires a documented watermark column")
        query_ready = False
    elif isinstance(ingestion_mode, str) and ingestion_mode.casefold() == "incremental":
        watermark_pattern = re.compile(
            rf"(?<![A-Za-z0-9_])\[?{re.escape(str(watermark))}\]?(?![A-Za-z0-9_])",
            re.IGNORECASE,
        )
        if not watermark_pattern.search(query):
            warnings.append(
                f"incremental extraction SQL does not filter on watermark {watermark!r}"
            )
            query_ready = False
            query = (
                "-- DRAFT ONLY: incremental SQL must apply the documented watermark.\n"
                f"-- TODO: add an approved predicate for watermark {watermark!r}.\n"
                + query
            )

    connection_env = (
        source_configuration.get("Connection Ref (Env Var)")
        if source_configuration
        else None
    )
    connection_configured = (
        isinstance(connection_env, str)
        and bool(os.environ.get(connection_env))
    )

    contract = {
        "apiVersion": API_VERSION,
        "kind": SOURCE_CONTRACT_KIND,
        "metadata": {
            "name": source_id,
            "status": "draft",
            "sourceSystem": metadata["sourceSystem"],
            "sourceSchema": metadata["sourceSchema"],
            "sourceTable": metadata["sourceTable"],
            "sourceWorkbook": metadata.get("sourceWorkbook"),
            "mappingMetadata": source_metadata_file,
            "owner": source_configuration.get("Source Owner") if source_configuration else None,
            "schemaChangeApprover": (
                source_configuration.get("Schema Change Approver")
                if source_configuration
                else None
            ),
        },
        "spec": {
            "connection": {
                "connector": source_configuration.get("Connector Type") if source_configuration else None,
                "platformVersion": source_configuration.get("Source Platform / Version") if source_configuration else None,
                "databaseCatalog": source_configuration.get("Database / Catalog") if source_configuration else None,
                "defaultSchema": source_configuration.get("Default Schema") if source_configuration else None,
                "referenceEnv": source_configuration.get("Connection Ref (Env Var)") if source_configuration else None,
                "authenticationMethod": source_configuration.get("Authentication Method") if source_configuration else None,
                "referenceConfiguredAtBuild": connection_configured,
            },
            "mappingSourceObject": {
                "schema": metadata["sourceSchema"],
                "table": metadata["sourceTable"],
            },
            "sourceObject": {
                "schema": str(
                    (
                        _optional_value(ingestion_configuration.get("Source Schema"))
                        if ingestion_configuration
                        else None
                    )
                    or metadata["sourceSchema"]
                ),
                "table": str(
                    (
                        _optional_value(ingestion_configuration.get("Source Table"))
                        if ingestion_configuration
                        else None
                    )
                    or metadata["sourceTable"]
                ),
            },
            "columns": columns,
            "schemaDiscovery": {
                "documentedStatus": (
                    _optional_value(ingestion_configuration.get("Discrepancy Status"))
                    if ingestion_configuration
                    else None
                ),
                "discoveredColumnCount": (
                    _optional_value(ingestion_configuration.get("Discovered Columns Count"))
                    if ingestion_configuration
                    else None
                ),
                "approval": (
                    _optional_value(ingestion_configuration.get("Approval Date & Approver"))
                    if ingestion_configuration
                    else None
                ),
                "runtimeStatus": (
                    "discrepancy"
                    if missing_mapped_columns or count_mismatch
                    else "mappedFieldsMatched"
                    if discovered_columns
                    else "notRun"
                ),
                "columns": discovered_columns,
                "missingMappedColumns": sorted(missing_mapped_columns),
                "columnCountMismatch": bool(count_mismatch),
            },
            "ingestion": {
                "mode": ingestion_mode,
                "watermarkColumn": watermark,
                "initialValuePolicy": (
                    _optional_value(ingestion_configuration.get("Initial Value Policy"))
                    if ingestion_configuration
                    else None
                ),
                "lateArrivingUpdateBehavior": (
                    _optional_value(ingestion_configuration.get("Late-Arriving Update Behavior"))
                    if ingestion_configuration
                    else None
                ),
                "deleteHandling": (
                    _optional_value(ingestion_configuration.get("Delete Handling"))
                    if ingestion_configuration
                    else None
                ),
                "extractionFilterOrSqlOverride": (
                    _optional_value(ingestion_configuration.get("Extraction Filter / SQL Override"))
                    if ingestion_configuration
                    else None
                ),
                "filterReasonAndOwner": (
                    _optional_value(ingestion_configuration.get("Filter Reason & Owner"))
                    if ingestion_configuration
                    else None
                ),
                "queryFile": sql_file,
                "queryReady": query_ready,
            },
            "unresolved": [
                *([] if connection_configured else [
                    "connection environment variable must be configured at runtime"
                ]),
            ] + (
                [] if discovered_columns
                else ["source column types and nullability require live source discovery"]
            ) + warnings,
        },
    }
    return contract, query, warnings
