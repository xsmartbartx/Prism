# Prism

**Self-hosted data platform — import, model, query, and visualize data declaratively.**

Prism replaces the spreadsheet-and-shared-drive reporting estate with a deterministic, auditable, AI-friendly data platform. **Drop a file, get a chart, share a link** — with complete lineage, drift detection, and zero-trust security.

## Core Thesis

- **An import is a compiled contract, not a copy.** A binding is reviewable, diffable, replayable, and a source that changes shape breaks it loudly.
- **A chart is a specification, not a picture.** One declarative grammar drives screen, export, and embed identically.
- **The AI proposes, the engine disposes.** Every agent output crosses the same validation path as untrusted user input.

## Status

**Phase 0 — Walking Skeleton (❄️ Complete)** · **241 tests passing** · **93% coverage**

| Deliverable | Status | Description |
|---|---|---|
| Type System v0 | ✅ | Integer, Float, String, Date, Boolean — locale-aware parsing/formatting |
| Binding Schema v0 | ✅ | ColumnContract, SourceBinding, validation, serialization |
| Structure Detector v0 | ✅ | CSV header detection, data region detection, confidence scoring |
| Type Inference v0 | ✅ | Ranked candidates, ambiguity detection → blocks publication |
| Query Compiler & Executor v0 | ✅ | QuerySpec → ExecutionPlan → ResultSet (filter/group/aggregate/sort) |
| View Spec v0 | ✅ | Declarative mark/encoding/scales grammar (bar, line, table) |
| SVG Renderer v0 | ✅ | Deterministic SVG output for bar, line, and table charts |
| Catalog & Audit Log | ✅ | Searchable index + append-only event record |
| Sharing v0 | ✅ | Signed, revocable, expiring share tokens |
| End-to-End Pipeline | ✅ | CSV → detect → infer → query → render → share |
| Container Deployment | ✅ | Dockerfile + docker-compose for single-node hosting |

### Phase 0 Exit Criterion (met)

> A non-technical user can drop a CSV file, confirm inference decisions, build a correct chart, and share it — with every step traceable through the audit log.

## Quick Start

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Run the full test suite (241 tests)
pytest

# Run with coverage
pytest --cov=core --cov=data --cov=presentation --cov=catalog --cov-report=term-missing
```

## End-to-End Example

```python
from data.detection.csv import detect_structure
from data.detection.inference import TypeInferenceEngine
from data.query.spec import QuerySpec, AggregationSpec, AggFunction
from data.query.compiler import QueryCompiler
from data.query.executor import QueryExecutor
from presentation.spec.view_spec import ViewSpec, MarkType, EncodingChannel, Encoding
from presentation.render.svg_renderer import SvgRenderer
from catalog import CatalogIndex, ArtifactType, ShareManager

# 1. Detect structure
structure = detect_structure("dept,name,salary\nEng,Alice,70000\nMkt,Bob,60000")

# 2. Infer types
inference = TypeInferenceEngine().infer_dataset(column_data)

# 3. Query — sum salary by department
spec = QuerySpec(dimensions=["dept"],
    measures=[AggregationSpec(column="salary", function=AggFunction.SUM)])
plan = QueryCompiler(dataset_columns=set(column_data.keys())).compile(spec).plan
result = QueryExecutor().execute(plan, rows)

# 4. Render as SVG
svg = SvgRenderer().render(ViewSpec(mark=MarkType.BAR, encodings=[
    Encoding(channel=EncodingChannel.X, field="dept"),
    Encoding(channel=EncodingChannel.Y, field="salary"),
]), list(result.rows))

# 5. Catalog + Share
catalog = CatalogIndex()
chart = catalog.register("Salary Chart", ArtifactType.CHART)
token = ShareManager().create_share(chart.id, ArtifactType.CHART, expires_in_hours=24)
```

## Container Deployment

```bash
cd deploy
docker compose up -d --build
```

See `deploy/Dockerfile` and `deploy/compose.yml`.

## Repository Structure

```
core/          Type system, validation, errors, detection primitives
data/          Ingestion (detection, inference) + query (spec, compiler, executor)
presentation/  View spec schema + SVG renderer
catalog/       Searchable index, audit log, share tokens
schemas/       Declarative document contracts (source bindings)
deploy/        Dockerfile, compose file
tests/         241 unit + integration tests
docs/          Architecture (prism-architecture-and-vision.md) + ADR-0003
```

## Architecture

See `docs/prism-architecture-and-vision.md` for the full architecture document and `docs/ADR-0003-dataset-and-visualization-model.md` for the dataset and visualization model.

## License

Proprietary. See `LICENSE`.