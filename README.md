# Agent-Driven Data Platform

This project turns the source-to-target mapping workbook into reviewable YAML
metadata, draft source/entity contracts, and SQL. The workbook is the initial
source of truth for documented mappings; generated artefacts do not replace
source-system discovery or approved business definitions.

## Build Everything

Install the project and its dependencies:

```shell
python -m pip install -e .
```

Run the complete workbook-to-SQL build:

```shell
python -m framework.build
```

This reads `s2t.xlsx`, generates and validates mapping metadata, then writes
source/entity contract drafts and SQL. Set different input/output paths when
needed:

```shell
python -m framework.build \
  --workbook path/to/s2t.xlsx \
  --metadata-dir path/to/metadata \
  --contracts-dir path/to/contracts \
  --sql-dir path/to/warehouse/sql
```

Add `--verbose` to print each row-level mapping warning; warnings are also
recorded in the metadata manifest.

Live SQL Server column discovery is optional and requires the `sqlserver`
extra, the Microsoft ODBC driver, and the connection environment variables
named in `source_systems`:

```shell
python -m pip install -e ".[sqlserver]"
python -m framework.build --discover-source-schema
```

This reads `INFORMATION_SCHEMA` and primary-key metadata. Connection values are
used only at runtime and are never copied to generated YAML.

Use the CLI only when you want to run or validate an individual stage:

```shell
python -m framework.cli generate-metadata
python -m framework.cli validate-metadata
python -m framework.cli generate-contracts
```

The build is also available as `python framework/build.py`.

## Run in Microsoft Fabric

The project is a Python package, not a built-in Fabric item type. Install it as
a custom library in a Fabric **Environment**, then call it from a Fabric
notebook. A Data Factory pipeline can run that notebook. See Microsoft's
guidance on [Fabric environments](https://learn.microsoft.com/fabric/data-engineering/create-and-use-environment),
[custom libraries](https://learn.microsoft.com/fabric/data-engineering/environment-manage-library),
[notebooks](https://learn.microsoft.com/fabric/data-engineering/how-to-use-notebook),
and [Notebook activities](https://learn.microsoft.com/fabric/data-factory/notebook-activity).

### 1. Build the Python wheel

From the repository root, build and test the distribution:

```shell
python -m pip wheel --no-deps --wheel-dir dist .
python -m unittest discover -s tests -v
```

The wheel is written to `dist/`; the filename includes the package version
from `pyproject.toml`. Build and retain a new, versioned wheel whenever the
package changes. You can optionally test-install it locally:

```shell
python -m pip install --no-deps dist/fabric_data_platform_framework-0.1.0-py3-none-any.whl
```

### 2. Add the package to a Fabric Environment

In a Fabric workspace with capacity:

1. Create an **Environment**.
2. Under **Custom libraries**, upload the wheel from `dist/`.
3. Add `openpyxl` and `PyYAML` as Python dependencies. These are the package's
   runtime dependencies; the wheel build command above deliberately does not
   bundle them.
4. Publish the Environment. Use **Full** publish mode for a stable library
   snapshot in scheduled or pipeline runs.

See Microsoft's guidance for the current [library sources and publish modes](https://learn.microsoft.com/fabric/data-engineering/environment-manage-library#select-publish-mode-for-libraries).
If your workspace restricts outbound access, make the dependencies available
through an approved private feed or upload compatible custom wheels.

### 3. Import and configure the notebook

Import [ContractBuilder.Notebook.ipynb](./fabric/ContractBuilder.Notebook.ipynb)
into the workspace. In the notebook:

1. Attach the Environment you published.
2. Attach the target Lakehouse and pin it as the **default Lakehouse**.
3. Upload the S2T workbook to the Lakehouse **Files** area.

The template expects the workbook at `Files/s2t.xlsx` by default. Its parameter
cell defines:

| Parameter | Default | Description |
|---|---|---|
| `workbook_path` | `s2t.xlsx` | Relative path to the workbook under Lakehouse `Files`. |
| `output_dir` | `contract-build` | Relative output directory under Lakehouse `Files`. |
| `discover_source_schema` | `False` | Whether to attempt optional live SQL Server discovery. |

Run the notebook. It calls `framework.fabric.run_fabric_build` and writes the
generated files under `Files/contract-build/metadata/`,
`Files/contract-build/contracts/`, and
`Files/contract-build/warehouse/sql/`. Paths are relative to the mounted
Lakehouse `Files` directory; absolute paths and parent-directory traversal are
rejected. The generated SQL is a reviewable artifact, not an executed query.

### 4. Orchestrate it with a Fabric pipeline (optional)

Create a Data Factory pipeline, add a **Notebook** activity, and select the
imported notebook. Override its base parameters when needed, using the names
above—for example, set `workbook_path` to `incoming/mapping.xlsx` when the
workbook is in `Files/incoming/`. The pipeline identity needs access to the
notebook, Environment, Lakehouse, and input/output data. Review Microsoft's
notes about [notebook execution identity](https://learn.microsoft.com/fabric/data-engineering/how-to-use-notebook#security-context-of-running-notebook),
especially before scheduling or running in production.

### Scope and limitations

- The Fabric adapter handles the mounted Lakehouse Files paths. It does not
  create Fabric items, deploy SQL, or execute generated SQL in a Warehouse.
- Review and validate generated SQL against the chosen Fabric target before
  deployment. A Lakehouse SQL analytics endpoint is read-only for table data
  changes; use an appropriate Warehouse or Spark workflow for writes.
- `discover_source_schema` is off by default. It currently uses SQL Server
  `pyodbc`; this requires the optional package, a compatible ODBC driver, and
  configured connectivity in the Fabric runtime. Validate those prerequisites
  before enabling it. This option is not a general Fabric source-discovery
  adapter.

## Generated Files

The output keeps entity and source-table metadata separate:

```text
metadata/
  _manifest.yaml
  entities/
    dim_customer.yaml
    fct_orders.yaml
  sources/
    <system>/
      <schema>/
        <table>.yaml
```

Entity files use `kind: EntityMapping` and retain every non-empty worksheet row,
including section headings. Each row records its original Excel row number.
Worksheet names beginning `dim_` or `dimension_` are labelled as dimensions;
`fct_` or `fact_` names are labelled as facts. Other names remain unclassified.
Source files use `kind: SourceTableMapping`; each source mapping includes the
entity, worksheet, row, target field, source field text, and original row data.
Repeated uses of a source table are retained as separate mappings.

The manifest uses `kind: MetadataManifest` and lists the source workbook,
generated entity and source files, mapping counts, explicit entity-to-source
dependency edges, and row-level warnings. It contains no generation timestamp,
so unchanged inputs produce stable YAML.
Generated YAML is parsed and structurally validated before generation reports
success. Validate it again independently with:

```shell
python -m framework.cli validate-metadata --metadata-dir metadata
```

When present, the `source_systems`, `source_ingestion`, `entity_definitions`,
`entity_relationships`, `governance`, and `traceability` worksheets are retained
under `enrichment` in the metadata manifest and consumed by the contract build.

## Generated Contract Drafts and SQL

The full build writes source contracts and source extraction queries under
`contracts/source/` and `warehouse/sql/source/`. Entity contract drafts and
SQL under their documented target schema are written under
`contracts/entity/` and `warehouse/sql/<target-schema>/`.
`contracts/_manifest.yaml` lists generated files and entity SQL still needing
decisions.

Source contracts preserve mapped and physical extraction objects, source
configuration, connection environment-variable names, ingestion policy, mapped
columns, and provenance. Optional SQL Server discovery adds source types,
nullability, lengths, precision/scale, and primary keys; differences in mapped
column presence or documented counts are recorded instead of overwritten.
Source extraction SQL uses a workbook override when present, otherwise simple
explicit source field names. Incremental SQL is marked not-ready unless it
applies the documented watermark. A ready query is mechanically complete, not
verified against a production source.

Entity contracts retain workbook data types, key flags, mandatory flags,
calculations, transformations, and row provenance without inventing missing
values. Documented join predicates are rendered into entity SQL. The generator
does not infer missing aliases, joins, generated keys, or business rules;
entities with unresolved fields receive a draft SQL file with the remaining
decisions. `sqlReady` means SQL is complete from documented mappings, not that
it has been checked against a live warehouse. Incremental source queries are
marked not-ready if they do not apply the documented watermark.

The workbook must contain the mapping headers `Attribute Type`, `Field`,
`Field Type`, `Source System`, `Source Schema`, `Source Table`, and
`Source Field(s)`. Duplicate headers and missing required headers stop
generation. Incomplete row mappings are preserved and reported as warnings so
they can be reviewed rather than silently discarded.

## Inference Boundaries

Source column types, nullability, connection details, load strategy, and
business transformation rules are not inferred from target-field metadata.
The source YAML preserves documented mapping information and provenance; a
future source adapter can add discovered metadata and report disagreements.
Credentials and secrets must not be written to generated YAML.

Generated contracts and SQL are reviewable drafts; this CLI does not deploy
pipelines or execute SQL in Microsoft Fabric.

## Development Checks

Run the offline tests:

```shell
python -m unittest discover -s tests -v
```