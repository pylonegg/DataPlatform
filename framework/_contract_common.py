"""Shared paths, metadata loading, and serialization for contract generation."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

if __package__:
    from framework.contract_mapping import safe_filename

else:
    from contract_mapping import safe_filename


API_VERSION = "data.example/v1"

CONTRACT_MANIFEST_KIND = "GeneratedContractManifest"

SOURCE_CONTRACT_KIND = "SourceContractDraft"

ENTITY_CONTRACT_KIND = "EntityContractDraft"

SQL_IDENTIFIER = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_ $@#]*$")

SOURCE_TYPE_MAP = {
    "char": "string",
    "varchar": "string",
    "nchar": "string",
    "nvarchar": "string",
    "text": "string",
    "ntext": "string",
    "uniqueidentifier": "string",
    "tinyint": "integer",
    "smallint": "integer",
    "int": "integer",
    "bigint": "integer",
    "decimal": "decimal",
    "numeric": "decimal",
    "money": "decimal",
    "smallmoney": "decimal",
    "float": "float",
    "real": "float",
    "bit": "boolean",
    "date": "date",
    "datetime": "datetime",
    "datetime2": "datetime",
    "smalldatetime": "datetime",
    "datetimeoffset": "datetime",
    "time": "time",
    "binary": "binary",
    "varbinary": "binary",
    "image": "binary",
    "timestamp": "binary",
    "rowversion": "binary",
}

def _read_yaml(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as file:
            return yaml.safe_load(file)
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"Unable to read metadata YAML {path}: {error}") from error

def _write_yaml(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

def _write_sql(path: Path, statement: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(statement.rstrip() + "\n", encoding="utf-8")

def _path_component(value: str) -> str:
    return safe_filename(value.strip())

def _source_id(source_system: str, source_schema: str, source_table: str) -> str:
    return f"{source_system}.{source_schema}.{source_table}"

def _normalized_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())

def _enrichment_rows(manifest: dict[str, Any], sheet_name: str) -> list[dict[str, Any]]:
    enrichment = manifest.get("enrichment", {})
    if not isinstance(enrichment, dict):
        return []
    rows = enrichment.get(sheet_name, [])
    return rows if isinstance(rows, list) else []

def _find_source_configuration(
    manifest: dict[str, Any],
    source_system: str,
) -> dict[str, Any] | None:
    for row in _enrichment_rows(manifest, "source_systems"):
        if str(row.get("Source System Name", "")).casefold() == source_system.casefold():
            return row
    return None

def _find_ingestion_configuration(
    manifest: dict[str, Any],
    source_system: str,
    source_schema: str,
    source_table: str,
) -> dict[str, Any] | None:
    expected_table = _normalized_name(f"{source_schema}_{source_table}")
    matches = [
        row
        for row in _enrichment_rows(manifest, "source_ingestion")
        if str(row.get("Source System", "")).casefold() == source_system.casefold()
        and _normalized_name(row.get("Source Table")) == expected_table
    ]
    if len(matches) > 1:
        raise ValueError(
            f"Multiple source_ingestion rows match "
            f"{source_system}.{source_schema}.{source_table}."
        )
    return matches[0] if matches else None

def _optional_value(value: Any) -> Any:
    if value is None or (isinstance(value, str) and value.strip().casefold() in {"", "n/a", "na", "none"}):
        return None
    return value

def _metadata_entries(
    metadata_dir: Path,
) -> tuple[
    dict[str, Any],
    list[tuple[dict[str, Any], dict[str, Any]]],
    list[tuple[dict[str, Any], dict[str, Any]]],
]:
    manifest_path = metadata_dir / "_manifest.yaml"
    manifest = _read_yaml(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("kind") != "MetadataManifest":
        raise ValueError(f"{manifest_path}: expected a MetadataManifest.")

    entities: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for entry in manifest.get("entities", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            raise ValueError(f"{manifest_path}: invalid entity entry {entry!r}.")
        entity_path = metadata_dir / entry["file"]
        entity = _read_yaml(entity_path)
        if not isinstance(entity, dict) or entity.get("kind") != "EntityMapping":
            raise ValueError(f"{entity_path}: expected an EntityMapping.")
        entities.append((entry, entity))

    sources: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for entry in manifest.get("sources", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            raise ValueError(f"{manifest_path}: invalid source entry {entry!r}.")
        source_path = metadata_dir / entry["file"]
        source = _read_yaml(source_path)
        if not isinstance(source, dict) or source.get("kind") != "SourceTableMapping":
            raise ValueError(f"{source_path}: expected a SourceTableMapping.")
        sources.append((entry, source))

    return manifest, entities, sources

def _quote_identifier(identifier: str) -> str:
    if not SQL_IDENTIFIER.fullmatch(identifier):
        raise ValueError(f"Unsupported SQL identifier {identifier!r}.")
    return f"[{identifier}]"

def _sql_name(value: str) -> str:
    return _quote_identifier(value)
