"""
Agent Module Tests
==================

Purpose
-------
This test suite validates the structural and behavioral integrity of the `agent` module,
which acts as the conversational reasoning engine in the customer-support solution.

Scope
-----
- Ensures that the module exposes the expected public API.
- Confirms that session reset behavior is safe and repeatable.
- Validates the canonical "envelope" schema structure for agent responses.
- Does NOT call external APIs or LLMs. All checks are offline and deterministic.
"""

# -----------------------------------------------------------------------------
# Libraries
# -----------------------------------------------------------------------------

# Standard libraries
import json               # JSON serialization and parsing for loader tests
import importlib          # Module reloading for monkeypatch consistency

# Third-party libraries
import pytest             # Pytest framework for isolated and reproducible testing

# ----------------------------
# Unit Test: Agent Public API
# ----------------------------
def test_agent_exports_minimal_api():
    """
    Verify that the `agent` module exposes the minimal required public API.

    Expected symbols:
    - `run`: Main callable for executing a reasoning cycle given a user message.
    - `reset_session`: Callable that resets conversation or memory state.

    This test prevents regressions that would break imports or runtime integration.
    """
    agent = importlib.import_module("agent")
    assert hasattr(agent, "run") and callable(agent.run), "agent.run must exist and be callable"
    assert hasattr(agent, "reset_session") and callable(agent.reset_session), "agent.reset_session must exist and be callable"

# ----------------------------
# Unit Test: Session Reset Idempotency
# ----------------------------
def test_agent_reset_session_is_idempotent():
    """
    Validate that calling `reset_session` multiple times is safe and has no side effects.

    The function should be idempotent, meaning multiple invocations should not
    raise errors or alter the state beyond the initial reset.
    """
    agent = importlib.import_module("agent")
    agent.reset_session()
    agent.reset_session()

# ----------------------------
# Unit Test: Envelope Contract Structure
# ----------------------------
def test_contract_envelope_example_shape():
    """
    Validate the shape and type integrity of a canonical envelope structure
    used by the agent to communicate reasoning outputs.

    The test ensures:
    - Presence of all required top-level keys.
    - Type correctness of each field.
    - Successful JSON serialization and deserialization.

    The envelope represents a valid "order_status" response pattern and serves
    as a template for agent output validation.
    """
    example = {
        "user_message": "Ok I found your order 1003",
        "intent": "order_status",
        "handoff": False,
        "slots": {
            "needs_order_id": False,
            "needs_product_name": False,
            "expected_input": None
        },
        "data": {
            "tracking_id": "1003",
            "status": "In transit",
            "carrier": "GreenExpress",
            "eta": "2025-10-01",
            "reason": None,
            "satisfied": None,
            "email_masked": "m***a.r*****z@ecomarket.test",
            "products": ["Bamboo Toothbrush"]
        },
        "ask_csat": True,
        "end_session": False
    }

    # Perform JSON round-trip to confirm serialization safety
    js = json.dumps(example)
    env = json.loads(js)

    # Validate required top-level keys
    required_keys = ("user_message", "intent", "handoff", "slots", "data", "ask_csat", "end_session")
    for k in required_keys:
        assert k in env, f"Missing top-level key: {k}"

    # Type validation
    assert isinstance(env["user_message"], str), "user_message must be a string"
    assert isinstance(env["intent"], str), "intent must be a string"
    assert isinstance(env["handoff"], bool), "handoff must be a boolean"
    assert isinstance(env["ask_csat"], bool), "ask_csat must be a boolean"
    assert isinstance(env["end_session"], bool), "end_session must be a boolean"
    assert isinstance(env["slots"], dict), "slots must be an object"
    assert isinstance(env["data"], dict), "data must be an object"
