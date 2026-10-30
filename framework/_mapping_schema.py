"""Constants defining the generated mapping metadata format."""

from __future__ import annotations

API_VERSION = "data.example/v1"

MANIFEST_KIND = "MetadataManifest"

ENTITY_KIND = "EntityMapping"

SOURCE_KIND = "SourceTableMapping"

REQUIRED_HEADERS = frozenset({
    "Attribute Type",
    "Field",
    "Field Type",
    "Source System",
    "Source Schema",
    "Source Table",
    "Source Field(s)",
})

SUPPORTING_SHEETS = {
    "source_systems": frozenset({
        "Source System Name",
        "Connector Type",
        "Database / Catalog",
        "Connection Ref (Env Var)",
    }),
    "source_ingestion": frozenset({
        "Source System",
        "Source Schema",
        "Source Table",
        "Ingestion Mode",
    }),
    "entity_definitions": frozenset({
        "Target Entity Name",
        "Target Schema",
        "Target Table",
        "Target Layer",
        "Business Key / Grain",
        "Load Strategy",
    }),
    "entity_relationships": frozenset({
        "Source Entity / Alias",
        "Target / Lookup Entity Alias",
        "Join Type",
        "Complete Join Predicate",
    }),
    "governance": frozenset({
        "Rule ID",
        "Target Entity",
        "Target Field",
        "Check Type / Rule Name",
        "Rule Logic / Expression",
    }),
    "traceability": frozenset({
        "Entity / Module",
        "Mapping Owner",
        "Business Approver",
        "Technical Approver",
        "Review Status",
    }),
}
