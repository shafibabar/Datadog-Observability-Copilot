"""Specs for the EC knowledge layer's loader and the shipped data files.

Two concerns live here:
  - the loader must be TOLERANT (a missing directory or a malformed file
    degrades to an empty/partial knowledge base, never a startup crash — the
    same contract build_monitors_index already honours), and
  - the committed data files must stay structurally intact and free of the
    client names that were scrubbed on the way in.
"""
from __future__ import annotations

import json

import pytest

from app.knowledge.loader import (
    DATA_DIR,
    SOURCES,
    KnowledgeBase,
    load_knowledge,
)


# --- loader tolerance ------------------------------------------------------

def test_missing_directory_yields_empty_base_not_an_error(tmp_path):
    kb = load_knowledge(tmp_path / "does-not-exist")
    assert kb.is_empty
    assert kb.loaded == ()
    assert kb.monitors_dictionary == {}


def test_malformed_file_is_skipped_and_recorded_others_still_load(tmp_path):
    (tmp_path / "monitors_dictionary.json").write_text("{not json at all", encoding="utf-8")
    (tmp_path / "errors.json").write_text(json.dumps({"repositories": {}}), encoding="utf-8")

    kb = load_knowledge(tmp_path)

    assert "errors" in kb.loaded
    assert "monitors_dictionary" not in kb.loaded
    assert "monitors_dictionary" in kb.failed
    assert kb.errors == {"repositories": {}}


def test_a_file_that_is_not_an_object_is_treated_as_malformed(tmp_path):
    # A JSON array parses fine but every consumer here indexes by key.
    (tmp_path / "examples.json").write_text("[1, 2, 3]", encoding="utf-8")
    kb = load_knowledge(tmp_path)
    assert "examples" in kb.failed
    assert kb.examples == {}


def test_partial_directory_loads_what_is_there(tmp_path):
    (tmp_path / "examples.json").write_text(json.dumps({"examples": []}), encoding="utf-8")
    kb = load_knowledge(tmp_path)
    assert kb.loaded == ("examples",)
    assert not kb.is_empty
    assert kb.nlp_grammar == {}


def test_every_source_name_maps_to_an_attribute():
    kb = KnowledgeBase()
    for name in SOURCES:
        assert hasattr(kb, name), f"KnowledgeBase is missing an attribute for {name}"


# --- the shipped data ------------------------------------------------------

@pytest.fixture(scope="module")
def shipped() -> KnowledgeBase:
    return load_knowledge()


def test_all_five_sources_ship_and_load(shipped):
    assert set(shipped.loaded) == set(SOURCES)
    assert shipped.failed == {}


def test_shipped_files_live_in_the_package(shipped):
    for name in SOURCES:
        assert (DATA_DIR / f"{name}.json").exists()


def test_grammar_carries_every_repository_and_the_full_lifecycle(shipped):
    repos = shipped.nlp_grammar["repositories"]
    assert len(repos) == 12

    stages = shipped.nlp_grammar["stageLifecycle"]["stages"]
    assert [s["order"] for s in stages] == list(range(1, 12))
    assert stages[0]["stage"] == "ingested"
    assert stages[-1]["stage"] == "reported"


def test_metrics_nlp_carries_intents_and_entities(shipped):
    intents = {i["id"] for i in shipped.metrics_nlp["nlpInterface"]["intents"]}
    assert {"GET_THROUGHPUT", "GET_LATENCY", "GET_ERRORS", "GET_LAG"} <= intents

    entities = {e["name"] for e in shipped.metrics_nlp["nlpInterface"]["entities"]}
    assert {"SERVICE", "OBJECT", "METRIC_TYPE", "TIME_RANGE"} <= entities


def test_monitors_dictionary_carries_monitors_and_detection_gaps(shipped):
    assert len(shipped.monitors_dictionary["monitors"]) >= 20
    cases = shipped.monitors_dictionary["detectionGaps"]["cases"]
    assert any("backed up" in c["userAsk"] for c in cases)


def test_examples_corpus_is_populated(shipped):
    assert len(shipped.examples["examples"]) >= 40


def test_client_names_were_scrubbed_from_every_shipped_file(shipped):
    """Env/tenant/channel CODES are deliberately kept — the resolver needs them
    to build real queries. The named institutions are not."""
    for name in SOURCES:
        blob = (DATA_DIR / f"{name}.json").read_text(encoding="utf-8").lower()
        assert "morgan stanley" not in blob
        assert "schwab" not in blob


def test_scrubbing_left_the_resolvable_codes_intact(shipped):
    blob = json.dumps(shipped.monitors_dictionary)
    assert "ep-ms-prod" in blob
    assert "ec-alerts-ms-p1" in blob
