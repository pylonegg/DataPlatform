"""Validate generated source/entity contracts and SQL artifacts."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

if __package__:
    from framework._contract_common import (
        API_VERSION, CONTRACT_MANIFEST_KIND, ENTITY_CONTRACT_KIND,
        SOURCE_CONTRACT_KIND, _read_yaml,
    )

else:
    from _contract_common import (
        API_VERSION, CONTRACT_MANIFEST_KIND, ENTITY_CONTRACT_KIND,
        SOURCE_CONTRACT_KIND, _read_yaml,
    )


def _validate_contract_document(document: Any, source: str) -> list[str]:
    if not isinstance(document, dict):
        return [f"{source}: contract must be a YAML mapping."]

    errors = []
    if document.get("apiVersion") != API_VERSION:
        errors.append(f"{source}: apiVersion must be {API_VERSION!r}.")
    kind = document.get("kind")
    if kind not in {SOURCE_CONTRACT_KIND, ENTITY_CONTRACT_KIND}:
        return errors + [f"{source}: unsupported contract kind {kind!r}."]

    metadata = document.get("metadata")
    spec = document.get("spec")
    if not isinstance(metadata, dict):
        errors.append(f"{source}: metadata must be a mapping.")
        metadata = {}
    if not isinstance(spec, dict):
        errors.append(f"{source}: spec must be a mapping.")
        spec = {}
    if metadata.get("status") != "draft":
        errors.append(f"{source}: metadata.status must be 'draft'.")

    if kind == SOURCE_CONTRACT_KIND:
        for field in ("name", "sourceSystem", "sourceSchema", "sourceTable", "sourceWorkbook"):
            value = metadata.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{source}: metadata.{field} must be a non-empty string.")
        connection = spec.get("connection")
        if not isinstance(connection, dict):
            errors.append(f"{source}: spec.connection must be a mapping.")
        columns = spec.get("columns")
        if not isinstance(columns, list):
            errors.append(f"{source}: spec.columns must be a list.")
        else:
            for index, column in enumerate(columns):
                label = f"{source}: spec.columns[{index}]"
                if not isinstance(column, dict):
                    errors.append(f"{label} must be a mapping.")
                    continue
                if not isinstance(column.get("name"), str) or not column["name"].strip():
                    errors.append(f"{label}.name must be a non-empty string.")
                if column.get("dataType") is not None and not isinstance(column.get("dataType"), str):
                    errors.append(f"{label}.dataType must be a string or null.")
                nullable = column.get("nullable")
                if nullable is not None and not isinstance(nullable, bool):
                    errors.append(f"{label}.nullable must be a boolean or null.")
        ingestion = spec.get("ingestion")
        if not isinstance(ingestion, dict):
            errors.append(f"{source}: spec.ingestion must be a mapping.")
        elif (
            not isinstance(ingestion.get("queryFile"), str)
            or not isinstance(ingestion.get("queryReady"), bool)
        ):
            errors.append(f"{source}: ingestion queryFile and queryReady are required.")
    else:
        for field in ("name", "sourceWorksheet", "sourceWorkbook"):
            value = metadata.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{source}: metadata.{field} must be a non-empty string.")
        if metadata.get("entityType") not in {None, "dimension", "fact"}:
            errors.append(f"{source}: metadata.entityType must be dimension, fact, or null.")
        attributes = spec.get("attributes")
        if not isinstance(attributes, list):
            errors.append(f"{source}: spec.attributes must be a list.")
        else:
            for index, attribute in enumerate(attributes):
                label = f"{source}: spec.attributes[{index}]"
                if not isinstance(attribute, dict):
                    errors.append(f"{label} must be a mapping.")
                    continue
                if not isinstance(attribute.get("name"), str) or not attribute["name"].strip():
                    errors.append(f"{label}.name must be a non-empty string.")
                nullable = attribute.get("nullable")
                if nullable is not None and not isinstance(nullable, bool):
                    errors.append(f"{label}.nullable must be a boolean or null.")
        dependencies = spec.get("dependsOn")
        if not isinstance(dependencies, list) or not all(
            isinstance(value, str) and value.strip() for value in dependencies
        ):
            errors.append(f"{source}: spec.dependsOn must be a list of source IDs.")
        execution = spec.get("execution")
        if not isinstance(execution, dict) or not isinstance(execution.get("sqlReady"), bool):
            errors.append(f"{source}: spec.execution.sqlReady must be a boolean.")

    return errors

def validate_generated_artifacts(contracts_dir: Path, sql_dir: Path) -> list[str]:
    manifest_path = contracts_dir / "_manifest.yaml"
    try:
        manifest = _read_yaml(manifest_path)
    except ValueError as error:
        return [str(error)]
    if not isinstance(manifest, dict) or manifest.get("kind") != CONTRACT_MANIFEST_KIND:
        return [f"{manifest_path}: expected a {CONTRACT_MANIFEST_KIND}."]

    errors = []
    if manifest.get("apiVersion") != API_VERSION:
        errors.append(f"{manifest_path}: apiVersion must be {API_VERSION!r}.")
    metadata_manifest_reference = manifest.get("sourceMetadataManifest")
    if not isinstance(metadata_manifest_reference, str):
        errors.append(f"{manifest_path}: sourceMetadataManifest must be a path.")
    else:
        try:
            metadata_manifest = _read_yaml(contracts_dir / metadata_manifest_reference)
        except ValueError as error:
            errors.append(str(error))
        else:
            if not isinstance(metadata_manifest, dict) or metadata_manifest.get("kind") != "MetadataManifest":
                errors.append(f"{manifest_path}: sourceMetadataManifest is not a MetadataManifest.")
    contracts = manifest.get("contracts")
    if not isinstance(contracts, list):
        return [f"{manifest_path}: contracts must be a list."]
    for entry in contracts:
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            errors.append(f"{manifest_path}: invalid contract entry {entry!r}.")
            continue
        relative_path = PurePosixPath(entry["file"])
        if relative_path.is_absolute() or ".." in relative_path.parts:
            errors.append(f"{manifest_path}: invalid contract path {entry['file']!r}.")
            continue
        expected_kind = {
            "source": SOURCE_CONTRACT_KIND,
            "entity": ENTITY_CONTRACT_KIND,
        }.get(relative_path.parts[0])
        if expected_kind is None or entry.get("kind") != expected_kind:
            errors.append(f"{manifest_path}: contract kind/path mismatch for {entry['file']!r}.")
            continue
        path = contracts_dir.joinpath(*relative_path.parts)
        try:
            document = _read_yaml(path)
        except ValueError as error:
            errors.append(str(error))
            continue
        errors.extend(_validate_contract_document(document, str(path)))
    sql_files = manifest.get("sqlFiles")
    if not isinstance(sql_files, list):
        errors.append(f"{manifest_path}: sqlFiles must be a list.")
        return errors
    for entry in sql_files:
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            errors.append(f"{manifest_path}: invalid SQL file entry {entry!r}.")
            continue
        relative_path = PurePosixPath(entry["file"])
        if relative_path.is_absolute() or ".." in relative_path.parts:
            errors.append(f"{manifest_path}: invalid SQL path {entry['file']!r}.")
            continue
        path = sql_dir.joinpath(*relative_path.parts)
        if not path.is_file():
            errors.append(f"{path}: generated SQL file is missing.")
        elif not isinstance(entry.get("ready"), bool):
            errors.append(f"{manifest_path}: SQL entry {entry['file']!r} needs a boolean ready value.")
        elif not path.read_text(encoding="utf-8").strip():
            errors.append(f"{path}: generated SQL file is empty.")
    return errors
