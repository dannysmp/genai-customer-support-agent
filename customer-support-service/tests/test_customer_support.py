"""
Unit tests for Customer Support Service
=======================================================

Purpose
-------
Validate that example envelopes for the supported flows follow the
current JSON contract implemented in the service. These tests provide
a fast regression check when modifying prompts or model configuration.

Scope
-----
- Structural validation of required keys and value types.
- No live model calls or external dependencies.

Notes
-----
These unit tests focus on structure. Schema-based validation and CI integration
can be added for extended coverage.
"""

# -----------------------------------------------------------------------------
# Libraries
# -----------------------------------------------------------------------------

# Standard libraries
import json               # JSON serialization and parsing for loader tests

# Third-party libraries
import pytest             # Pytest framework for isolated and reproducible testing

# ----------------------------
# Allowed Intents from the Service
# ----------------------------
ALLOWED_INTENTS = {
    "order_status",
    "return_request",
    "request_tracking_id",
    "missing_tracking_id",
    "nlu_failed_order",
    "nlu_failed_return",
    "no_orders",
    "order_not_found",
    "present_order_delivered_ask_return_intent",
    "present_order_in_transit",
    "present_order_ready_for_pickup",
    "confirm_proceed_and_ask_review_another",
    "unknown",
    "smalltalk",
    "greeting",
    "goodbye",
}

# ----------------------------
# Example Envelopes
# ----------------------------
# Examples mirror the current Envelope fields seen in the service:
# - user_message: str
# - end_session: bool
# - intent: str
# - lang: Optional[str]
# - next_expected: Optional[str]
# - order_context: Optional[dict]
# - order: Optional[dict]
# - items: Optional[list[str]]
# - items_detail: Optional[list[dict]]
# - requested_items: Optional[list[str]]
# - return_validation: Optional[dict]
# - masked_email: Optional[str]

order_status_envelope = json.dumps(
    {
        "user_message": "Found order 1003. Carrier GreenExpress. Estimated delivery 2025-09-18.",
        "end_session": False,
        "intent": "order_status",
        "lang": "en",
        "order_context": {
            "tracking_id": "1003",
            "status": "In transit",
            "carrier": "GreenExpress",
            "eta": "2025-09-18",
        },
        "order": {"id": "1003"},
        "masked_email": "m***a.r*****z@ecomarket.test",
        "items": ["Bamboo Toothbrush", "Natural Toothpaste"],
        "items_detail": [
            {"sku": "BT-001", "name": "Bamboo Toothbrush"},
            {"sku": "NT-010", "name": "Natural Toothpaste"},
        ],
    }
)

returns_envelope = json.dumps(
    {
        "user_message": "The item Bamboo Toothbrush is eligible for return within 30 days if unopened.",
        "end_session": False,
        "intent": "return_request",
        "lang": "en",
        "requested_items": ["Bamboo Toothbrush"],
        "return_validation": {
            "policy_window_days": 30,
            "is_eligible": True,
            "reason": None,
        },
        "masked_email": "s***a.s****z@ecomarket.test",
        "order": {"id": "1007"},
        "order_context": {
            "tracking_id": "1007",
            "status": "Delivered",
            "carrier": "EcoShip",
            "delivered_at": "2025-09-05",
        },
    }
)

# ----------------------------
# Contract Helpers
# ----------------------------
REQUIRED_MINIMAL_KEYS = ("user_message", "intent", "end_session")

def _parse(js: str) -> dict:
    """
    Parse a JSON string into a Python dictionary.

    Returns
    -------
    dict
        Decoded JSON object. Raises json.JSONDecodeError if invalid.
    """
    return json.loads(js)

# ----------------------------
# Unit Test: Minimal Contract
# ----------------------------
def test_order_status_has_required_minimal_keys():
    """
    Verify that the order status envelope exposes the minimal required keys.
    """
    data = _parse(order_status_envelope)
    for k in REQUIRED_MINIMAL_KEYS:
        assert k in data

def test_returns_has_required_minimal_keys():
    """
    Verify that the returns envelope exposes the minimal required keys.
    """
    data = _parse(returns_envelope)
    for k in REQUIRED_MINIMAL_KEYS:
        assert k in data

# ----------------------------
# Unit Test: Value Types and Intent Constraints
# ----------------------------
def test_order_status_value_types_and_intent():
    """
    Verify basic value types and intent for the order status envelope.
    """
    data = _parse(order_status_envelope)
    assert isinstance(data["user_message"], str)
    assert isinstance(data["end_session"], bool)
    assert data["intent"] in ALLOWED_INTENTS

def test_returns_value_types_and_intent():
    """
    Verify basic value types and intent for the returns envelope.
    """
    data = _parse(returns_envelope)
    assert isinstance(data["user_message"], str)
    assert isinstance(data["end_session"], bool)
    assert data["intent"] in ALLOWED_INTENTS

# ----------------------------
# Unit Test: Optional Blocks Shape
# ----------------------------
def test_order_status_optional_blocks_shape():
    """
    Validate optional blocks when present. Do not enforce presence.
    """
    data = _parse(order_status_envelope)

    if "order_context" in data and data["order_context"] is not None:
        ctx = data["order_context"]
        assert isinstance(ctx, dict)
        # Common optional keys that may appear for order status
        for k in ("tracking_id", "status", "carrier"):
            assert k in ctx

    if "items" in data and data["items"] is not None:
        items = data["items"]
        assert isinstance(items, list)
        if items:
            assert isinstance(items[0], str)

    if "items_detail" in data and data["items_detail"] is not None:
        detail = data["items_detail"]
        assert isinstance(detail, list)
        if detail:
            first = detail[0]
            assert isinstance(first, dict)
            assert "sku" in first and "name" in first
            assert isinstance(first["sku"], str)
            assert isinstance(first["name"], str)

def test_returns_optional_blocks_shape():
    """
    Validate optional blocks for a returns flow when present.
    """
    data = _parse(returns_envelope)

    if "requested_items" in data and data["requested_items"] is not None:
        req = data["requested_items"]
        assert isinstance(req, list)
        if req:
            assert isinstance(req[0], str)

    if "return_validation" in data and data["return_validation"] is not None:
        rv = data["return_validation"]
        assert isinstance(rv, dict)
        # Expected keys for a simple eligibility summary
        for k in ("is_eligible", "policy_window_days", "reason"):
            assert k in rv

    if "order_context" in data and data["order_context"] is not None:
        ctx = data["order_context"]
        assert isinstance(ctx, dict)
        for k in ("tracking_id", "status", "carrier"):
            assert k in ctx

# ----------------------------
# Smoke Test: JSON Roundtrip
# ----------------------------
def test_envelope_json_roundtrip():
    """
    Validate that example envelopes are valid JSON strings and round-trip correctly.
    """
    for js in (order_status_envelope, returns_envelope):
        obj = json.loads(js)
        re_js = json.dumps(obj)
        assert isinstance(re_js, str) and len(re_js) > 0
