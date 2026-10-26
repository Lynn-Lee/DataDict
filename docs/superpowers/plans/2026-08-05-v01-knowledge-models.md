# V0.1 Knowledge Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement DEV-TASKS T1.2 knowledge-layer metadata tables as SQLAlchemy models and an Alembic migration.

**Architecture:** Keep human-maintained knowledge tables separate from machine-maintained collection tables. Register every knowledge table in `KNOWLEDGE_TABLES` so later grant tests can prove `datadict_collector` has read-only access to this layer.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.0, Alembic, PostgreSQL JSONB and generated columns.

---

### File Structure

- Create `app/models/knowledge.py`: ORM models for `business_domain`, `domain_rule`, `tag`, `dict`, `asset_annotation`, `asset_tag_rel`, `annotation_history`, and `common_column_blacklist`.
- Modify `app/models/__init__.py`: import the new knowledge model module.
- Create `alembic/versions/20260805_0002_knowledge_metadata.py`: knowledge-layer migration depending on `20260805_0001`.
- Create `tests/models/test_knowledge_models.py`: metadata-level tests for registration, constraints, references, and generated search text.

### Task 1: RED Tests

- [x] Create tests that assert all 8 knowledge tables are registered in `Base.metadata` and `KNOWLEDGE_TABLES`.
- [x] Assert `asset_annotation.urn` is unique, `asset_annotation.search_text` is generated from `business_meaning`, `usage_note`, and `source_desc`.
- [x] Assert `tag` has a category/code uniqueness constraint and `common_column_blacklist.column_name` is unique.
- [x] Run `.venv/bin/pytest tests/models/test_knowledge_models.py -v` and confirm it fails because the tables do not exist yet.

### Task 2: GREEN Models

- [x] Add focused ORM models in `app/models/knowledge.py`.
- [x] Register the 8 table names in `KNOWLEDGE_TABLES`.
- [x] Import the module from `app/models/__init__.py`.
- [x] Run `.venv/bin/pytest tests/models/test_knowledge_models.py -v` and confirm it passes.

### Task 3: Alembic Migration

- [x] Add revision `20260805_0002`, `down_revision = "20260805_0001"`.
- [x] Create the 8 knowledge-layer tables and required indexes.
- [x] Add `idx_annotation_search_trgm` for `asset_annotation.search_text`.
- [x] Run `.venv/bin/alembic heads` and confirm `20260805_0002 (head)`.

### Task 4: Verify And Publish

- [x] Run `.venv/bin/pytest -v`.
- [x] Run `.venv/bin/ruff check app tests alembic`.
- [x] Run `.venv/bin/mypy app`.
- [x] Run `make test-gate`.
- [ ] Commit with `feat: add knowledge metadata models`.
- [ ] Push `main` to `origin`.
- [ ] Wait for GitHub Actions and report the result.

### Self-Review

- Spec coverage: this covers DEV-TASKS T1.2 only. It intentionally excludes `asset_embedding` because the task book places semantic search in V1.0, not T1.2.
- Placeholder scan: no placeholder steps remain.
- Type consistency: table names match DataDict-DEV-TASKS T1.2 and DataDict-PRD §5.2.
