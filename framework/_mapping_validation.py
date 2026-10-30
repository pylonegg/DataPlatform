"""Validate mapping manifests and their referenced YAML documents."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import yaml

if __package__:
    from framework._mapping_schema import (
        API_VERSION, ENTITY_KIND, MANIFEST_KIND, SOURCE_KIND, SUPPORTING_SHEETS,
    )

else:
    from _mapping_schema import (
        API_VERSION, ENTITY_KIND, MANIFEST_KIND, SOURCE_KIND, SUPPORTING_SHEETS,
    )


def _validate_artifact(document: Any, expected_kind: str, source: str) -> list[str]:
    errors = []
    if not isinstance(document, dict):
        return [f"{source}: YAML document must be a mapping."]
    if document.get("apiVersion") != API_VERSION:
        errors.append(f"{source}: apiVersion must be {API_VERSION!r}.")
    if document.get("kind") != expected_kind:
        errors.append(f"{source}: kind must be {expected_kind!r}.")

    metadata = document.get("metadata")
    spec = document.get("spec")
    if not isinstance(metadata, dict):
        errors.append(f"{source}: metadata must be a mapping.")
    if not isinstance(spec, dict):
        errors.append(f"{source}: spec must be a mapping.")
        return errors

    if expected_kind == ENTITY_KIND:
        for key in ("name", "sourceWorkbook", "sourceWorksheet"):
            if not isinstance(metadata, dict) or not isinstance(metadata.get(key), str) or not metadata[key].strip():
                errors.append(f"{source}: metadata.{key} must be a non-empty string.")
        if isinstance(metadata, dict) and metadata.get("entityType") not in {
            None,
            "dimension",
            "fact",
        }:
            errors.append(f"{source}: metadata.entityType must be 'dimension', 'fact', or null.")
        records = spec.get("records")
        if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
            errors.append(f"{source}: spec.records must be a list of mappings.")
        elif spec.get("recordCount") != len(records):
            errors.append(f"{source}: spec.recordCount does not match spec.records.")
    else:
        for key in ("sourceSystem", "sourceSchema", "sourceTable", "sourceWorkbook"):
            if not isinstance(metadata, dict) or not isinstance(metadata.get(key), str) or not metadata[key].strip():
                errors.append(f"{source}: metadata.{key} must be a non-empty string.")
        mappings = spec.get("mappings")
        if not isinstance(mappings, list) or not all(isinstance(item, dict) for item in mappings):
            errors.append(f"{source}: spec.mappings must be a list of mappings.")
        elif spec.get("mappingCount") != len(mappings):
            errors.append(f"{source}: spec.mappingCount does not match spec.mappings.")

    return errors

def _safe_manifest_path(output_dir: Path, relative_path: Any, category: str) -> Path | None:
    if not isinstance(relative_path, str):
        return None
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != category:
        return None
    return output_dir.joinpath(*path.parts)

def validate_metadata_directory(output_dir: Path) -> list[str]:
    """Validate the manifest and every generated entity/source YAML file."""
    manifest_path = output_dir / "_manifest.yaml"
    try:
        with manifest_path.open("r", encoding="utf-8") as file:
            manifest = yaml.safe_load(file)
    except (OSError, yaml.YAMLError) as error:
        return [f"{manifest_path}: unable to read YAML: {error}"]

    if not isinstance(manifest, dict):
        return [f"{manifest_path}: manifest must be a YAML mapping."]
    errors = []
    if manifest.get("apiVersion") != API_VERSION:
        errors.append(f"{manifest_path}: apiVersion must be {API_VERSION!r}.")
    if manifest.get("kind") != MANIFEST_KIND:
        errors.append(f"{manifest_path}: kind must be {MANIFEST_KIND!r}.")
    if not isinstance(manifest.get("sourceWorkbook"), str) or not manifest["sourceWorkbook"].strip():
        errors.append(f"{manifest_path}: sourceWorkbook must be a non-empty string.")

    entity_files: set[str] = set()
    source_files: set[str] = set()
    for category, kind in (("entities", ENTITY_KIND), ("sources", SOURCE_KIND)):
        artifacts = manifest.get(category)
        if not isinstance(artifacts, list):
            errors.append(f"{manifest_path}: {category} must be a list.")
            continue
        for entry in artifacts:
            if not isinstance(entry, dict):
                errors.append(f"{manifest_path}: each {category} entry must be a mapping.")
                continue
            artifact_path = _safe_manifest_path(output_dir, entry.get("file"), category)
            if artifact_path is None:
                errors.append(f"{manifest_path}: invalid {category} file path {entry.get('file')!r}.")
                continue
            relative_path = PurePosixPath(entry["file"]).as_posix()
            if category == "entities":
                entity_files.add(relative_path)
            else:
                source_files.add(relative_path)
            try:
                with artifact_path.open("r", encoding="utf-8") as file:
                    document = yaml.safe_load(file)
            except (OSError, yaml.YAMLError) as error:
                errors.append(f"{artifact_path}: unable to read YAML: {error}")
                continue
            errors.extend(_validate_artifact(document, kind, str(artifact_path)))

    dependencies = manifest.get("dependencies")
    if not isinstance(dependencies, list):
        errors.append(f"{manifest_path}: dependencies must be a list.")
    else:
        for index, dependency in enumerate(dependencies):
            label = f"{manifest_path}: dependencies[{index}]"
            if not isinstance(dependency, dict):
                errors.append(f"{label} must be a mapping.")
                continue
            if dependency.get("entity") not in entity_files:
                errors.append(f"{label}.entity must reference a listed entity file.")
            if dependency.get("source") not in source_files:
                errors.append(f"{label}.source must reference a listed source file.")

    enrichment = manifest.get("enrichment", {})
    if not isinstance(enrichment, dict):
        errors.append(f"{manifest_path}: enrichment must be a mapping.")
    else:
        for sheet_name, records in enrichment.items():
            if sheet_name not in SUPPORTING_SHEETS:
                errors.append(f"{manifest_path}: unknown enrichment sheet {sheet_name!r}.")
            if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
                errors.append(f"{manifest_path}: enrichment.{sheet_name} must be a list of mappings.")

    return errors
