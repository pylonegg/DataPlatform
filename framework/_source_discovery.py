"""Discover source columns and assemble mapped source-column metadata."""

from __future__ import annotations

import os
from typing import Any

if __package__:
    from framework._contract_common import (
        SOURCE_TYPE_MAP, SQL_IDENTIFIER, _optional_value,
    )

else:
    from _contract_common import SOURCE_TYPE_MAP, SQL_IDENTIFIER, _optional_value


def _source_column_mappings(source: dict[str, Any]) -> list[dict[str, Any]]:
    columns: dict[str, dict[str, Any]] = {}
    for mapping in source["spec"].get("mappings", []):
        raw_name = mapping.get("sourceFields")
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        name = raw_name.strip()
        column = columns.setdefault(name, {
            "name": name,
            "dataType": None,
            "nullable": None,
            "mappings": [],
            "queryEligible": bool(SQL_IDENTIFIER.fullmatch(name)),
        })
        column["mappings"].append({
            "entity": mapping.get("entity"),
            "targetField": mapping.get("targetField"),
            "worksheet": mapping.get("worksheet"),
            "excelRow": mapping.get("excelRow"),
        })
    return list(columns.values())

def discover_source_columns(cursor: Any, schema: str, table: str) -> list[dict[str, Any]]:
    """Read SQL Server column definitions and primary keys from INFORMATION_SCHEMA."""
    cursor.execute("""
        SELECT
            COLUMN_NAME,
            DATA_TYPE,
            IS_NULLABLE,
            CHARACTER_MAXIMUM_LENGTH,
            NUMERIC_PRECISION,
            NUMERIC_SCALE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ?
          AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
    """, schema, table)
    rows = cursor.fetchall()
    if not rows:
        raise ValueError(f"No source columns were discovered for {schema}.{table}.")

    cursor.execute("""
        SELECT kcu.COLUMN_NAME
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS AS tc
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE AS kcu
          ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
         AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
         AND tc.TABLE_NAME = kcu.TABLE_NAME
        WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
          AND tc.TABLE_SCHEMA = ?
          AND tc.TABLE_NAME = ?
    """, schema, table)
    primary_keys = {row[0].casefold() for row in cursor.fetchall()}

    columns = []
    for name, data_type, nullable, max_length, precision, scale in rows:
        normalized_type = SOURCE_TYPE_MAP.get(str(data_type).casefold())
        columns.append({
            "name": name,
            "dataType": normalized_type,
            "sourceDataType": data_type,
            "nullable": nullable == "YES",
            "maxLength": max_length,
            "precision": precision,
            "scale": scale,
            "primaryKey": str(name).casefold() in primary_keys,
        })
    return columns

def _discover_source_table(
    source_configuration: dict[str, Any] | None,
    source_metadata: dict[str, Any],
    ingestion_configuration: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if source_configuration is None:
        raise ValueError(
            f"No source_systems configuration exists for "
            f"{source_metadata['sourceSystem']!r}."
        )
    connector = str(source_configuration.get("Connector Type") or "").casefold()
    if "sql server" not in connector:
        raise ValueError(
            f"Live schema discovery currently supports SQL Server; "
            f"{source_configuration.get('Connector Type')!r} is not supported."
        )
    connection_env = source_configuration.get("Connection Ref (Env Var)")
    if not isinstance(connection_env, str) or not connection_env.strip():
        raise ValueError(
            f"No connection environment-variable name is configured for "
            f"{source_metadata['sourceSystem']!r}."
        )
    connection_string = os.environ.get(connection_env)
    if not connection_string:
        raise ValueError(
            f"Set {connection_env} before requesting live source schema discovery."
        )
    try:
        import pyodbc
    except ModuleNotFoundError as error:
        if error.name != "pyodbc":
            raise
        raise RuntimeError(
            "SQL Server schema discovery requires pyodbc; install the 'sqlserver' extra."
        ) from error

    schema = (
        _optional_value(ingestion_configuration.get("Source Schema"))
        if ingestion_configuration
        else None
    ) or source_metadata["sourceSchema"]
    table = (
        _optional_value(ingestion_configuration.get("Source Table"))
        if ingestion_configuration
        else None
    ) or source_metadata["sourceTable"]
    connection = None
    cursor = None
    try:
        connection = pyodbc.connect(connection_string)
        cursor = connection.cursor()
        return discover_source_columns(cursor, str(schema), str(table))
    except pyodbc.Error as error:
        raise ValueError(
            f"SQL Server schema discovery failed for {schema}.{table}: {error}"
        ) from error
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()
