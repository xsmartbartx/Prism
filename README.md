# Prism

**Self-hosted data platform — import, model, query, and visualize data declaratively.**

Prism replaces the spreadsheet-and-shared-drive reporting estate with a deterministic, auditable, AI-friendly data platform. Drop a file, get a chart, share a link — with complete lineage, drift detection, and zero-trust security.

## Core Thesis

- **An import is a compiled contract, not a copy.** A binding is reviewable, diffable, replayable, and a source that changes shape breaks it loudly.
- **A chart is a specification, not a picture.** One declarative grammar drives screen, export, and embed identically.
- **The AI proposes, the engine disposes.** Every agent output crosses the same validation path as untrusted user input.

## Status

Phase 0 — Walking Skeleton (in progress)

| Deliverable | Status |
|---|---|
| Type System v0 | ✅ Done — Integer, Float, String, Date, Boolean with locale-aware parsing |
| Binding Schema v0 | ✅ Done — ColumnContract, SourceBinding, validation, serialization |
| Structure Detector v0 | ✅ Done — CSV header detection, data region detection, confidence scoring |
| Type Inference v0 | 🔜 Next |
| Binding Compiler v0 | 🔜 Next |

## Quick Start

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest
```

## Repository Structure

```
core/          Type system, validation, errors
data/          Ingestion, modeling, query
presentation/  Charts, dashboards, exploration
security/      Policy, sandbox, pentest
insight/       Observability, agents, lineage
schemas/       Declarative document contracts
catalog/       Searchable metadata index
deploy/        Container definitions
tests/         Unit, integration, contract, fixtures
docs/          Architecture, ADRs, guides
```

## Architecture

See `docs/prism-architecture-and-vision.md` for the full architecture document and `docs/ADR-0003-dataset-and-visualization-model.md` for the dataset and visualization model.

## License

Proprietary. See `LICENSE`.