"""
RAG Module Tests
================

Purpose
-------
Validate the public contract and critical behaviors of the retrieval module:
- build_rag_context(query) always returns a string (possibly empty)
- Truncation respects MAX_CONTEXT_CHARS and ends with "..."
- Safe handling when no results are retrieved (empty context)
- Utility loaders return the expected formats for policy, orders, product catalog, and FAQs

Scope
-----
- Tests are fully self-contained and rely only on local data files located in `data`.
- These are executed entirely offline, requiring no internet connectivity or third-party services.
"""

# -----------------------------------------------------------------------------
# Libraries
# -----------------------------------------------------------------------------

# Standard libraries
import json               # JSON serialization and parsing for loader tests
import importlib          # Module reloading for monkeypatch consistency

# Third-party libraries
import pytest             # Pytest framework for isolated and reproducible testing

# Local modules
import rag                # RAG module under test

# ----------------------------
# Helper Functions
# ----------------------------

@pytest.fixture
def reload_rag():
    """
    Reload the rag module after monkeypatching globals.

    Rationale
    ---------
    Some implementations might read certain globals (e.g., limits) at import time.
    Reloading ensures patched values are applied consistently, keeping tests stable.
    """
    yield
    importlib.reload(rag)

# ----------------------------
# Unit Test: Public Contract
# ----------------------------

def test_build_rag_context_returns_string():
    """
    The public API must return a string for any input.
    Empty or non-empty is allowed, but the type must be str.
    """
    ctx = rag.build_rag_context("order status 1001")
    assert isinstance(ctx, str)

# ----------------------------
# Unit Test: Truncation Behavior
# ----------------------------

def test_build_rag_context_respects_max_chars(monkeypatch, reload_rag):
    """
    Output must not exceed MAX_CONTEXT_CHARS.
    If trailing truncation is applied, the string ends with "...".
    Implementations that pre-budget content may remain strictly below the cap. 
    Both behaviors are acceptable.
    """
    # Force long results without depending on the real index
    monkeypatch.setattr(rag, "_search", lambda q, k=4: ["x" * 500])

    # Lower the cap to reliably trigger size pressure in this test
    monkeypatch.setattr(rag, "MAX_CONTEXT_CHARS", 60)

    ctx = rag.build_rag_context("any query")
    assert isinstance(ctx, str)
    assert len(ctx) <= rag.MAX_CONTEXT_CHARS
    assert ctx.endswith("...") or len(ctx) < rag.MAX_CONTEXT_CHARS

# ----------------------------
# Unit Test: Empty Retrieval
# ----------------------------

def test_build_rag_context_empty_when_no_results(monkeypatch):
    """
    If no results are retrieved, the function must return an empty string.
    """
    monkeypatch.setattr(rag, "_search", lambda q, k=4: [])
    ctx = rag.build_rag_context("unknown query")
    assert ctx == ""

# ----------------------------
# Unit Test: Orders Loader
# ----------------------------

def test_load_orders_block_is_json_string():
    """
    load_orders_block must return a JSON-serialized string that parses to a list.
    """
    text = rag.load_orders_block()
    assert isinstance(text, str)

    # The content should parse cleanly. It may be "[]" if the dataset is empty.
    data = json.loads(text)
    assert isinstance(data, list)

# ----------------------------
# Unit Test: Policy Loader
# ----------------------------

def test_load_policy_block_is_text():
    """
    load_policy_block must return a UTF-8 decoded string.
    It is expected to be non-empty if the policy file exists.
    """
    policy = rag.load_policy_block()
    assert isinstance(policy, str)

    # If the file is present in `data`, it should not be blank.
    assert policy.strip() != ""

# ----------------------------
# Unit Test: Product Catalog Loader
# ----------------------------

def test_product_catalog_loader_valid_json():
    """
    The product catalog JSON file should load and parse successfully.
    Each entry must contain the expected base keys.
    """
    path = rag.PRODUCT_CATALOG_DB
    assert path.exists(), "Product catalog file is missing in data directory"

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, list)
    if data:
        first = data[0]
        assert "sku" in first and "name" in first, "Product entry missing required keys"
        assert isinstance(first["sku"], str), "Product 'sku' must be a string"
        assert isinstance(first["name"], str), "Product 'name' must be a string"

# ----------------------------
# Unit Test: FAQs Loader
# ----------------------------

def test_faqs_loader_contains_questions_and_answers():
    """
    The FAQs Markdown file should contain properly formatted entries
    with headings (###) and text content.
    """
    path = rag.FAQS_DOC
    assert path.exists(), "FAQs Markdown file is missing in data directory"

    text = path.read_text(encoding="utf-8")
    assert isinstance(text, str)
    assert "###" in text, "FAQs Markdown must contain at least one question heading"

# ----------------------------
# Smoke Test: Vector Store Initialization
# ----------------------------

def test_vectorstore_builds_and_search_works_smoke():
    """
    Minimal smoke test ensuring that internal retrieval is operational.
    The API surface is build_rag_context; we simply assert it returns a string.
    """
    ctx = rag.build_rag_context("returns policy")
    assert isinstance(ctx, str)

# ----------------------------
# Smoke Test: Order Signal
# ----------------------------

def test_orders_signal_is_searchable_smoke():
    """
    A lightweight query that *may* yield order-related context.
    This remains a smoke test and does not assert specific content to avoid
    brittle coupling with the local dataset.
    """
    ctx = rag.build_rag_context("1001")
    assert isinstance(ctx, str)
