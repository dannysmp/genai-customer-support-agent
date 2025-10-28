"""
Agentic Workflow Module

Overview
--------
- Deterministic rule based controller that drives the order and returns flow.
- Parses tracking identifiers from user input.
- Retrieves order data through public access functions.
- Maintains minimal in memory dialog state.
- Validates return eligibility per item using catalog metadata and delivery date.
- Emits a structured envelope for a separate NLG layer to render user text.

Runtime Contract
----------------
The module exposes a single public interface:
    run(user_text: str) -> Envelope

Business Flow
-------------
0) Ask for Language.
1) Ask for Tracking ID.
2) When provided, fetch order and show details.
3) If delivered, ask if the user wants to return items.
4) If the user wants returns, ask which items, validate each item, present reasons,
   and ask to proceed when at least one item is eligible. Proceed is always for the eligible subset.
   If the user proceeds, confirm that instructions will be sent by email.
   After either branch, ask to review another order and loop to step two when the answer is yes,
   otherwise end.
5) If the user does not want returns, ask to review another order and apply the same branching.

Session Model
-------------
Single in memory session for the current process.
"""

# -----------------------------------------------------------------------------
# Libraries
# -----------------------------------------------------------------------------

# Python future features
from __future__ import annotations                 # Postponed evaluation of type annotations

# Standard libraries
import re                                          # Regular expression parsing for simple intent cues
import unicodedata                                 # Normalization helper to compare accented text
from dataclasses import dataclass, field           # Lightweight state containers for session memory
from datetime import datetime, date                # Date handling for delivery parsing and window checks
from typing import List, Dict, Any, Optional       # Type hints for clarity and safety

# Third-party libraries
from pydantic import BaseModel                     # Data model and validation for the agent envelope

# Local modules
from rag import (                                  # Deterministic data access utilities
    get_order_by_tracking,                         # Order lookup by tracking identifier
    get_order_context,                             # Canonical order context string for grounding
    get_catalog_map,                               # Product catalog metadata map for return validation
    get_forbidden_categories,                      # Dynamic parser for forbidden product categories
)

# -----------------------------------------------------------------------------
# Data models
# -----------------------------------------------------------------------------

class Envelope(BaseModel):
    """
    Structured response produced by the agent.

    Purpose.
    Encapsulates dialog intent, control flags, and machine-readable payload so a higher layer can compose the final user text.

    NLG control.
    - nlg set to True indicates that user text should be rendered by a higher layer.
    - user_message remains empty in this module.
    - end_session set to True closes the conversation.

    Dialog control.
    - intent describes the next action for the NLG layer.
    - next_expected names the slot expected next.

    Payload control.
    - lang optional language code for downstream rendering ("en" or "es").
    - order_context is a deterministic order summary string.
    - order includes minimal order fields for grounding.
    - items lists item names in the current order.
    - items_detail lists dicts {name, quantity} for bullet rendering with quantities.
    - requested_items lists items selected by the user for return.
    - return_validation contains per item eligibility results.
    - masked_email optional masked customer email for return-instructions messaging.
    """
    # NLG control
    nlg: bool = True
    user_message: Optional[str] = None
    end_session: bool = False

    # Dialog control
    intent: Optional[str] = None
    next_expected: Optional[str] = None

    # Payload control
    lang: Optional[str] = None
    order_context: Optional[str] = None
    order: Optional[Dict[str, Any]] = None
    items: Optional[List[str]] = None
    items_detail: Optional[List[Dict[str, Any]]] = None
    requested_items: Optional[List[str]] = None
    return_validation: Optional[List[Dict[str, Any]]] = None
    masked_email: Optional[str] = None

@dataclass
class AgentSession:
    """
    In-memory session state for a single interactive conversation.

    Tracks the current order selection, delivery status, the last known list of items,
    and which confirmation questions are pending. The state resets when a new order
    becomes active.
    """
    lang: Optional[str] = None
    tracking_id: Optional[str] = None
    order_status: Optional[str] = None
    delivered_at: Optional[str] = None
    last_order_items: List[str] = field(default_factory=list)

    # Pending dialog stages
    awaiting_items_selection: bool = False
    awaiting_confirm_proceed: bool = False
    awaiting_review_another: bool = False
    last_requested_items: List[str] = field(default_factory=list)
    awaiting_tracking_id: bool = False
    last_order: Optional[Dict[str, Any]] = None

    def reset_for_new_order(self) -> None:
        """
        Clear transient dialog flags and cached fields for the next order selection.
        """
        self.order_status = None
        self.delivered_at = None
        self.last_order_items = []
        self.awaiting_items_selection = False
        self.awaiting_confirm_proceed = False
        self.awaiting_review_another = False
        self.last_requested_items = []
        self.awaiting_tracking_id = False
        self.last_order = None

# -----------------------------------------------------------------------------
# Session state
# -----------------------------------------------------------------------------

# Single session store for the current process
_SESSION = AgentSession()

def reset_session() -> None:
    """
    Reset the in-memory agent session state.

    Why here:
    - Placed next to the session definition to keep concerns co-located.
    - Exposed as a public function so the web service can trigger a clean slate
      without importing internals or mutating fields directly.
    """
    # Access the global session instance for reinitialization
    global _SESSION

    # Recreate the session object to clear all stored state, flags, and cached data
    _SESSION = AgentSession()

# -----------------------------------------------------------------------------
# Text parsing and validation helpers
# -----------------------------------------------------------------------------

# Tracking pattern for identifiers.
# Accepts alphanumeric characters and the dash character.
# Requires at least one digit and must have a length between 3 and 14 characters.
_TRACKING_RX = re.compile(r"(?=\b[A-Za-z0-9-]{3,14}\b)(?=.*\d)\b[A-Za-z0-9-]{3,14}\b")

def _detect_language_choice(text: str) -> Optional[str]:
    """
    Detect a user language choice.

    Accepts common self-reports for English or Spanish in either language.
    Returns "en" for English, "es" for Spanish, or None when unclear.
    """
    if not text:
        return None
    if re.search(r"\b(espa[nñ]ol|spanish)\b", text, re.IGNORECASE):
        return "es"
    if re.search(r"\b(ingl[eé]s|english)\b", text, re.IGNORECASE):
        return "en"
    return None

def _extract_tracking_id(text: str) -> Optional[str]:
    """
    Extract a tracking identifier from user text.

    Purpose
    -------
    Locate an alphanumeric sequence that matches the tracking format used for orders.
    The expression allows letters, digits, and dash characters and requires at least one digit.

    Parameters
    -------
    text is the raw user input possibly containing a tracking reference.

    Returns
    -------
    The extracted tracking identifier as a string when found, otherwise None.
    """
    if not text:
        return None
    m = _TRACKING_RX.search(text)
    return m.group(0) if m else None

def _normalize_text_token(text: str) -> str:
    """
    Normalize input text for uniform token comparison.

    Purpose
    -------
    Convert arbitrary user input into a canonical lowercase form without diacritics
    or redundant whitespace. This ensures consistent string matching between tokens
    regardless of accent marks, capitalization, or spacing.

    Parameters
    -------
    text is a raw string that may include uppercase letters, diacritics, or irregular spacing.

    Returns
    -------
    A lowercase string with all diacritics removed and consecutive whitespace collapsed
    into single spaces, suitable for reliable lexical comparison.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFD", text)
    without_marks = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    collapsed = re.sub(r"\s+", " ", without_marks)
    return collapsed.strip().lower()

def _normalize_list_from_text(text: str) -> List[str]:
    """
    Convert user text into a list of product names.

    Purpose
    -------
    Parse names separated by commas, line breaks, or simple conjunctions such as "and" or "y".
    This supports flexible free text input when a user lists multiple items.

    Parameters
    -------
    text is a free form string that may contain several product names.

    Returns
    -------
    A list of normalized product names stripped of extra spaces.
    """
    if not text:
        return []
    cleaned = re.sub(r"\b(y|and|&)\b", ",", text, flags=re.IGNORECASE)
    parts = re.split(r"[,\n]+", cleaned)
    names = [p.strip() for p in parts if p.strip()]
    return names

def _match_requested_to_order_items(requested: List[str], order_items: List[str]) -> List[str]:
    """
    Match user provided product names to items present in the order.

    Purpose
    -------
    Perform a case insensitive comparison to ensure that requested items
    correspond exactly to those available in the order list.

    Parameters
    -------
    requested is a list of product names provided by the user.
    order_items is a list of item names contained in the order.

    Returns
    -------
    A list of matching item names in canonical order.
    """
    if not requested or not order_items:
        return []
    order_lower = {_normalize_text_token(item): item for item in order_items}
    matched = []
    for r in requested:
        key = _normalize_text_token(r)
        if key in order_lower:
            matched.append(order_lower[key])
    return matched

# -----------------------------------------------------------------------------
# Policy parsing
# -----------------------------------------------------------------------------

# Cached list of forbidden product categories used for strict return validation.
_FORBIDDEN_CATEGORIES = {c.strip().lower() for c in (get_forbidden_categories() or [])}

# -----------------------------------------------------------------------------
# Return validation
# -----------------------------------------------------------------------------

def _validate_return_items(
    products: List[str],
    delivered_at: Optional[str],
    catalog_map: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Perform strict validation of item-level return eligibility based on delivery date,
    product metadata, and policy rules.

    Validation Logic
    ----------------
    An item is considered *eligible for return* only if **all** of the following
    conditions are satisfied:

      1. **Within time window** — The number of days since delivery is less than
         or equal to the product’s `return_window_days` value.
      2. **Non-perishable** — Items marked as perishable (`is_perishable=True`)
         are automatically ineligible, regardless of the time window.
      3. **Category not forbidden** — The product category is not included in the
         global `_FORBIDDEN_CATEGORIES` list derived from the return policy.

    Parameters
    ----------
    products : List[str]
        List of product names selected by the customer for return validation.
        Each product name must correspond to an entry in the product catalog.
    delivered_at : Optional[str]
        Delivery date in ISO format (`YYYY-MM-DD`). Used to calculate the
        elapsed time since the order was received.
    catalog_map : Dict[str, Dict[str, Any]]
        Dictionary mapping normalized product names (lowercase) to their
        catalog metadata, including at least:
            - `"category"` : str → Product category.
            - `"is_perishable"` : bool → Whether the product is perishable.
            - `"return_window_days"` : int → Allowed return window in days.

    Returns
    -------
    List[Dict[str, Any]]
        A list of dictionaries, one per product, containing:
            - `"product"` : str → The product name.
            - `"eligible"` : bool → Whether the item meets all return conditions.
            - `"reason"` : str → Explanation code for eligibility or rejection.
                * `"ok"` — Item is eligible.
                * `"insufficient_window_info"` — Missing delivery date or return window.
                * `"invalid_window_value"` — Non-numeric return window.
                * `"time_window_exceeded"` — Returned after allowed time frame.
                * `"perishable_not_returnable"` — Rejected due to perishability.
                * `"category_not_returnable"` — Rejected by policy category rule.
            - `"meta"` : Dict[str, Any] → Additional diagnostic details, including:
                * `"elapsed_days"` — Number of days since delivery.
                * `"catalog_window_days"` — Allowed return window in days.
                * `"category"` — Product category.
                * `"is_perishable"` — Boolean perishability flag.

    Notes
    -----
    - This function enforces a **strict all-conditions rule**: if any rule fails,
      the item is immediately rejected with the corresponding reason.
    - If `delivered_at` or `return_window_days` is missing, the item is considered
      ineligible and flagged as `"insufficient_window_info"`.
    - The logic is deterministic and free of side effects; it does not modify
      session or external state.
    """
    # Initialize validation results list
    results: List[Dict[str, Any]] = []

    # Parse and validate delivery date
    delivered_date: Optional[date] = None
    if delivered_at:
        try:
            delivered_date = datetime.strptime(delivered_at.strip(), "%Y-%m-%d").date()
        except Exception:
            delivered_date = None

    # Compute elapsed days since delivery (if available)
    today = date.today()
    elapsed = (today - delivered_date).days if delivered_date else None

    # Iterate through products and evaluate eligibility per item
    for name in products:
        meta = catalog_map.get(name.lower().strip(), {}) or {}
        category = (meta.get("category") or "").strip().lower()
        is_perishable = bool(meta.get("is_perishable", False))
        window = meta.get("return_window_days", None)

        # Validate presence of essential data
        if delivered_date is None or window is None:
            results.append({
                "product": name,
                "eligible": False,
                "reason": "insufficient_window_info",
                "meta": {
                    "delivered_at": delivered_at or "unknown",
                    "catalog_window_days": window,
                    "category": category or "unknown",
                    "is_perishable": is_perishable,
                    "elapsed_days": elapsed if elapsed is not None else "unknown",
                },
            })
            continue

        # Parse numeric return window safely
        try:
            window_int = int(window)
        except Exception:
            results.append({
                "product": name,
                "eligible": False,
                "reason": "invalid_window_value",
                "meta": {
                    "delivered_at": delivered_at or "unknown",
                    "catalog_window_days": window,
                    "category": category or "unknown",
                    "is_perishable": is_perishable,
                    "elapsed_days": elapsed if elapsed is not None else "unknown",
                },
            })
            continue

        # Check time window validity
        if elapsed is None or elapsed > window_int:
            results.append({
                "product": name,
                "eligible": False,
                "reason": "time_window_exceeded",
                "meta": {
                    "elapsed_days": elapsed if elapsed is not None else "unknown",
                    "catalog_window_days": window_int,
                    "category": category or "unknown",
                    "is_perishable": is_perishable,
                },
            })
            continue

        # Reject perishable items
        if is_perishable:
            results.append({
                "product": name,
                "eligible": False,
                "reason": "perishable_not_returnable",
                "meta": {
                    "elapsed_days": elapsed,
                    "catalog_window_days": window_int,
                    "category": category or "unknown",
                    "is_perishable": is_perishable,
                },
            })
            continue

        # Reject items in forbidden categories
        if category and category in _FORBIDDEN_CATEGORIES:
            results.append({
                "product": name,
                "eligible": False,
                "reason": "category_not_returnable",
                "meta": {
                    "elapsed_days": elapsed,
                    "catalog_window_days": window_int,
                    "category": category,
                    "is_perishable": is_perishable,
                },
            })
            continue

        # All rules satisfied, mark as eligible
        results.append({
            "product": name,
            "eligible": True,
            "reason": "ok",
            "meta": {
                "elapsed_days": elapsed,
                "catalog_window_days": window_int,
                "category": category or "unknown",
                "is_perishable": is_perishable,
            },
        })

    # Return aggregated validation results
    return results

def _affirms(text: str) -> bool:
    """
    Detect affirmative intent in user input.

    Purpose
    -------
    Identify expressions such as yes, ok, sure, or similar words indicating agreement.
    """
    return bool(re.search(r"\b(s[ií]|yes|yeah|yup|ok|okay|sure|claro|adelante)\b", text, re.IGNORECASE))

def _declines(text: str) -> bool:
    """
    Detect negative intent in user input.

    Purpose
    -------
    Identify expressions such as no, nop, nope, or equivalent negations.
    """
    return bool(re.search(r"\b(no|nop|nope|negativo)\b", text, re.IGNORECASE))

def _mentions_return_intent(text: str) -> bool:
    """
    Detect whether the user mentions returning items.

    Purpose
    -------
    Capture expressions referring to the concept of a return or refund process.
    """
    return bool(re.search(r"\b(devolver|devoluci[oó]n|return|retornar)\b", text, re.IGNORECASE))

def _mentions_review_another(text: str) -> bool:
    """
    Detect intent to review another order.

    Purpose.
    Identify when the user requests to check a different order after finishing a previous one.
    """
    return bool(re.search(r"\b(otra|otro|another)\b.*\b(orden|order)\b", text, re.IGNORECASE))

def _items_detail_from_order(order: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build a UI-friendly list of items with quantities.

    Purpose
    -------
    Converts the raw `order["items"]` array into a normalized list of dicts:
    `[{"name": "<Product Name>", "quantity": <int>}, ...]`.

    Parameters
    ----------
    order : Dict[str, Any]
        Full order record containing an `items` list, where each element may
        include `name` and `quantity`.

    Returns
    -------
    List[Dict[str, Any]]
        Each element has the shape `{"name": str, "quantity": int}` and is safe
        for direct rendering in bullet lists.
    """
    return [
        {"name": str(it.get("name", "")).strip(), "quantity": int(it.get("quantity", 1))}
        for it in order.get("items", []) if str(it.get("name", "")).strip()
    ]

def _mask_email(email: str) -> str:
    """
    Purpose
    -------
    Produce a privacy-safe masked representation of a customer's email for NLG.

    Parameters
    ----------
    email : str
        Raw email address from the order record.

    Returns
    -------
    str
        Masked email of the form "<first2>***@..." (e.g., "an***@...").
        If parsing fails, returns "...@...".
    """
    if not email or "@" not in email:
        return "...@..."
    local, _domain = email.split("@", 1)
    local = (local or "").strip()
    head = local[:2] if len(local) >= 2 else (local[:1] or "")
    return f"{head}***@..."

# -----------------------------------------------------------------------------
# Core agent orchestration
# -----------------------------------------------------------------------------

def _envelope(
    intent: str,
    *,
    user_message: Optional[str] = None,
    nlg: Optional[bool] = None,
    **payload: Any,
) -> Envelope:
    """
    Build a standardized dialog envelope for message orchestration.

    Purpose
    -------
    Create a unified container that encapsulates both control metadata and
    contextual payload required by the conversational flow. The envelope ensures
    determinism and consistency when messages are passed between layers of the
    dialog manager or external clients.

    The function automatically injects the current session language into the
    payload, allowing Natural Language Generation (NLG) components to render
    responses in the appropriate language without additional preprocessing.

    Parameters
    ----------
    intent : str
        High-level intent identifier describing the dialog action to execute
        (e.g., "check_order_status", "initiate_return", "fallback").
    user_message : Optional[str], default=None
        Raw user utterance captured from the interface. If omitted, it implies
        a system-initiated message rather than a user prompt.
    nlg : Optional[bool], default=None
        Boolean flag indicating whether the output should trigger NLG
        rendering. Defaults to True when `user_message` is not provided.
    **payload : Any
        Additional key-value data providing contextual information such as
        `order_context`, `items`, or `return_validation`.

    Returns
    -------
    Envelope
        A structured and language-aware container that encapsulates both the
        dialog intent and contextual metadata, ready for serialization or
        downstream processing.
    """
    if "lang" not in payload:
        payload["lang"] = _SESSION.lang

    resolved_nlg = nlg if nlg is not None else user_message is None

    return Envelope(
        intent=intent,
        user_message=user_message,
        nlg=resolved_nlg,
        **payload,
    )

def _format_no_eligible_message(
    order: Dict[str, Any],
    items_detail: List[Dict[str, Any]],
    validation: List[Dict[str, Any]],
    lang: Optional[str],
) -> str:
    """
    Generate a structured message when no order items qualify for return.

    Purpose.
    Construct a clear and localized message (English or Spanish) summarizing
    the order's current state, relevant delivery details, and per-item reasons
    for ineligibility. This ensures consistent user communication when return
    validation rules disqualify all products in an order.

    Parameters.
    order: Dictionary containing order metadata (status, carrier, delivery date, etc.).
    items_detail: List of dictionaries with product-level information (name, quantity).
    validation: List of validation results with reason codes for each item.
    lang: Optional language code ("en" or "es") for message localization.

    Returns.
    A human-readable multi-line string summarizing order details and the reasons
    why each item is not eligible for return.
    """

    # Determine active language. Fallback to English if not provided or unsupported
    lang = (lang or _SESSION.lang or "en") or "en"
    lang = lang if lang in {"en", "es"} else "en"

    # Normalize key order fields for consistent display
    status = (order.get("status") or "").strip()
    carrier = (order.get("carrier") or "").strip()
    delivered_at = (order.get("delivered_at") or "").strip()
    eta = (order.get("eta") or "").strip()
    tracking_id = (order.get("tracking_id") or "").strip()

    header_parts: List[str] = []
    order_ref_es = f"la orden {tracking_id}" if tracking_id else "la orden"
    order_ref_en = f"order {tracking_id}" if tracking_id else "this order"

    # Build localized message headers
    if lang == "es":
        if status:
            header_parts.append(f"Estado de la orden: {status}.  ")
        if carrier:
            header_parts.append(f"Transportista: {carrier}.  ")
        if delivered_at:
            header_parts.append(f"Entregada el {delivered_at}.  ")
        elif eta:
            header_parts.append(f"Fecha estimada de entrega: {eta}.  ")
        intro = f"Ningún artículo de {order_ref_es} es elegible para devolución."
        section_title = "Artículos de la orden:"
        qty_label = "cant"
        reason_map = {
            "insufficient_window_info": "Falta la fecha de entrega o la ventana de devoluciones, así que no podemos procesar la devolución.",
            "invalid_window_value": "La información de la ventana de devolución es inválida para este producto.",
            "time_window_exceeded": "La ventana de devolución ya venció.",
            "perishable_not_returnable": "Los artículos perecederos no se pueden devolver.",
            "category_not_returnable": "Esta categoría no es elegible para devoluciones.",
        }
        default_reason = "No es elegible para devolución."
        closing_question = "¿Deseas revisar otra orden?"
    else:
        if status:
            header_parts.append(f"Order status: {status}.  ")
        if carrier:
            header_parts.append(f"Carrier: {carrier}.  ")
        if delivered_at:
            header_parts.append(f"Delivered on {delivered_at}.  ")
        elif eta:
            header_parts.append(f"Estimated arrival: {eta}.  ")

        intro = f"No items from {order_ref_en} are eligible for return."
        section_title = "Order items:"
        qty_label = "qty"
        reason_map = {
            "insufficient_window_info": "Missing delivery date or return window, so we can’t process the return.",
            "invalid_window_value": "Return window data is invalid for this product.",
            "time_window_exceeded": "The return window has already passed.",
            "perishable_not_returnable": "Perishable items can’t be returned.",
            "category_not_returnable": "This category is not eligible for returns.",
        }
        default_reason = "Not eligible for return."
        closing_question = "Would you like to check another order?"

    # Create a fast lookup between product names and validation entries
    validation_map = {str(v.get("product", "")).strip(): v for v in validation}

    # Build per-item bullet point lines
    bullet_lines: List[str] = []
    for item in items_detail:
        name = str(item.get("name", "")).strip()
        if not name:
            continue

        detail = validation_map.get(name)
        reason_code = (detail or {}).get("reason")
        reason_text = reason_map.get(reason_code, default_reason)

        # Normalize and validate quantity display
        quantity = item.get("quantity")
        try:
            quantity_int = int(quantity) if quantity is not None else None
        except Exception:
            quantity_int = None
        quantity_display = quantity_int if quantity_int is not None else quantity or 0

        bullet_lines.append(
            f"•  {name} ({qty_label}: {quantity_display}) — {reason_text}  "
        )

    summary_lines: List[str] = []
    summary_lines.extend(header_parts)
    if header_parts:
        summary_lines.append("")
    summary_lines.append(intro)
    summary_lines.append("")
    summary_lines.append(section_title)
    summary_lines.append("")
    summary_lines.extend(bullet_lines)
    if bullet_lines:
        summary_lines.append("")
    summary_lines.append(closing_question)
    return "\n".join(summary_lines)

def _format_validation_confirmation(
    requested_items: List[str],
    validation: List[Dict[str, Any]],
    lang: Optional[str],
) -> str:
    """
    Generate a concise multilingual confirmation message after item validation.

    Purpose
    -------
    Create a user-facing summary confirming the eligibility status of the
    items the user selected for return. Each product is annotated with whether
    it can be returned and, if not, the specific reason explaining why. The
    message is automatically localized in English or Spanish.

    Parameters
    ----------
    requested_items : List[str]
        List of item names provided by the user for validation.
    validation : List[Dict[str, Any]]
        Validation results containing eligibility flags and reason codes
        for each product (e.g., 'eligible': True/False, 'reason': 'time_window_exceeded').
    lang : Optional[str]
        Desired output language ("en" or "es"). Defaults to the current
        session language or English if not specified.

    Returns
    -------
    str
        A formatted, multi-line confirmation message summarizing the validation
        results for each item, including eligibility and reason text, ending with
        a question prompting the user to continue with the return process.
    """

    lang = (lang or _SESSION.lang or "en") or "en"
    lang = lang if lang in {"en", "es"} else "en"

    validation_map = {str(v.get("product", "")).strip(): v for v in validation}

    if lang == "es":
        intro = "Validación de artículos seleccionados:"
        eligible_text = "Es elegible para devolución."
        default_reason = "No es elegible para devolución."
        reason_map = {
            "insufficient_window_info": "Falta la fecha de entrega o la ventana de devoluciones, así que no podemos procesar la devolución.",
            "invalid_window_value": "La información de la ventana de devolución es inválida para este producto.",
            "time_window_exceeded": "La ventana de devolución ya venció.",
            "perishable_not_returnable": "Los artículos perecederos no se pueden devolver.",
            "category_not_returnable": "Esta categoría no es elegible para devoluciones.",
        }
        question = "¿Deseas proceder con la devolución ahora?"
    else:
        intro = "Validation for the selected items:"
        eligible_text = "Eligible for return."
        default_reason = "Not eligible for return."
        reason_map = {
            "insufficient_window_info": "Missing delivery date or return window, so we can’t process the return.",
            "invalid_window_value": "Return window data is invalid for this product.",
            "time_window_exceeded": "The return window has already passed.",
            "perishable_not_returnable": "Perishable items can’t be returned.",
            "category_not_returnable": "This category is not eligible for returns.",
        }
        question = "Would you like to proceed with the return now?"

    bullet_lines: List[str] = []
    for name in requested_items:
        clean_name = str(name or "").strip()
        if not clean_name:
            continue
        detail = validation_map.get(clean_name)
        if not detail:
            continue
        if detail.get("eligible"):
            bullet_lines.append(f"•  {clean_name} — {eligible_text}  ")
        else:
            reason_code = detail.get("reason")
            reason_text = reason_map.get(reason_code, default_reason)
            bullet_lines.append(f"•  {clean_name} — {reason_text}  ")

    if not bullet_lines:
        if lang == "es":
            bullet_lines.append("•  No se identificaron artículos para validar.  ")
        else:
            bullet_lines.append("•  No items were identified for validation.  ")

    lines: List[str] = [intro, "", *bullet_lines, "", question]
    return "\n".join(lines)

def _format_order_payload(order: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a normalized payload with order summary and item names.

    Purpose
    -------
    Provide deterministic fields that ground downstream rendering or UI.
    Includes a compact order context string and minimal order attributes.

    Parameters
    ----------
    order
        Dictionary for a single order record.

    Returns
    -------
    dict
        Mapping with order_context, a minimal order subobject, and the list of
        item names present in the order.
    """
    tracking_id = order.get("tracking_id")
    return {
        "order_context": get_order_context(tracking_id),
        "order": {
            "tracking_id": tracking_id,
            "status": order.get("status"),
            "carrier": order.get("carrier"),
            "eta": order.get("eta"),
            "delivered_at": order.get("delivered_at"),
        },
        "items": [str(it.get("name", "")).strip() for it in order.get("items", [])],
    }

def _bootstrap_order_in_session(order: Dict[str, Any]) -> None:
    """
    Store minimal order state in the session for later turns.

    Purpose
    -------
    Cache key attributes from the selected order so the agent can route the
    flow without repeated database lookups.

    Parameters
    ----------
    order
        Dictionary representing the selected order.
    """
    _SESSION.reset_for_new_order()
    _SESSION.tracking_id = str(order.get("tracking_id"))
    _SESSION.order_status = (order.get("status") or "").strip().lower()
    _SESSION.delivered_at = (order.get("delivered_at") or "").strip() or None
    _SESSION.last_order_items = [str(it.get("name", "")).strip() for it in order.get("items", [])]

def _extract_and_switch_order(user_text: str) -> Optional[Envelope]:
    """
    Detect a tracking identifier in user input and route to that order.

    Behavior
    --------
    When a valid tracking token is present the agent loads the order, updates
    session state, and returns the next dialog step based on delivery status.

    Parameters
    ----------
    user_text
        Raw message received from the user.

    Returns
    -------
    Envelope or None
        Envelope with the next intent when a token is found.
        None when no tracking token is present.
    """
    tid = _extract_tracking_id(user_text)
    if not tid:
        return None

    order = get_order_by_tracking(tid)
    if not order:
        # Token found but no matching record. Ask again and include the candidate
        _SESSION.awaiting_review_another = True
        _SESSION.awaiting_tracking_id = False
        return _envelope(
            intent="order_not_found_ask_review_another",
            next_expected="review_another",
            order={"tracking_id_candidate": tid},
        )

    # Cache state for the new order and prepare payload
    _bootstrap_order_in_session(order)
    payload = _format_order_payload(order)

    # Branch by delivery status to keep dialog deterministic
    if _SESSION.order_status == "delivered":
        return _envelope(
            intent="present_order_delivered_ask_return_intent",
            next_expected="return_intent",
            **payload,
        )
    else:
        _SESSION.awaiting_review_another = True
        return _envelope(
            intent="present_order_not_delivered_ask_review_another",
            next_expected="review_another",
            **payload,
        )

def run(user_text: str) -> Envelope:
    """
    Main entry point for the agent logic.

    Behavior
    --------
    The agent follows a structured conversation flow divided into stages.
    If a tracking ID is detected, it pivots directly to the corresponding order.
    Otherwise, it continues based on the current session state.
    Always returns an envelope describing the next dialog action.

    Parameters
    ----------
    user_text
        Raw message received from the user.

    Returns
    -------
    Envelope
        Structured response describing the next dialog step and payload.
    """
    text = (user_text or "").strip()

    # Step 0. Handle language selection
    # Ask the user to choose the language if not set yet
    if _SESSION.lang is None:
        choice = _detect_language_choice(text)
        if choice is None:
            return _envelope(
                intent="ask_language_preference",
                next_expected="language",
            )
        else:
            _SESSION.lang = choice
            _SESSION.awaiting_tracking_id = True
            return _envelope(
                intent="request_tracking_id",
                next_expected="tracking_id",
            )

    # Step 1. Pivot immediately if a tracking ID is detected
    # Attempt to locate the order and branch logic accordingly
    tracking_id = _extract_tracking_id(text)

    # If a tracking ID is present in the text, attempt to find the order and pivot
    if tracking_id:
        order = get_order_by_tracking(tracking_id)

        # Order found. Update session and branch by delivery status
        if order:
            _SESSION.tracking_id = str(order.get("tracking_id"))
            _SESSION.order_status = (order.get("status") or "").strip().lower()
            _SESSION.last_order_items = [str(it.get("name", "")).strip() for it in order.get("items", [])]
            _SESSION.delivered_at = (order.get("delivered_at") or "").strip() or None
            _SESSION.last_order = order
            _SESSION.awaiting_tracking_id = False

            # Build detailed item list for bullet rendering
            items_detail = _items_detail_from_order(order)

            # Step 3. Delivered order. Ask if the user wants to return items
            if _SESSION.order_status == "delivered":
                # Do not offer returns if all items are already ineligible by time, perishable and category policy
                if _SESSION.last_order_items:
                    catalog_map = get_catalog_map()
                    results = _validate_return_items(_SESSION.last_order_items, _SESSION.delivered_at, catalog_map)
                    if results and all(not r.get("eligible") for r in results):
                        _SESSION.awaiting_review_another = True
                        payload = _format_order_payload(order)
                        payload["items_detail"] = items_detail
                        message = _format_no_eligible_message(
                            payload.get("order", {}),
                            items_detail,
                            results,
                            _SESSION.lang,
                        )
                        return _envelope(
                            intent="show_validation_none_eligible_ask_review_another",
                            next_expected="review_another",
                            requested_items=_SESSION.last_order_items,
                            return_validation=results,
                            user_message=message,
                            nlg=False,
                            **payload,
                        )
                _SESSION.awaiting_review_another = False
                return _envelope(
                    intent="present_order_delivered_ask_return_intent",
                    next_expected="return_intent",
                    items=_SESSION.last_order_items,
                    items_detail=items_detail,
                    order_status=_SESSION.order_status,
                )

            # Step 6. Order not delivered. Ask if the user wants to review another
            else:
                _SESSION.awaiting_review_another = True
                return _envelope(
                    intent="present_order_not_delivered_ask_review_another",
                    next_expected="review_another",
                    items=_SESSION.last_order_items,
                    items_detail=items_detail,
                    order_status=_SESSION.order_status,
                )

        # Order not found. Ask to review another order
        else:
            _SESSION.tracking_id = None
            _SESSION.awaiting_review_another = True
            _SESSION.awaiting_tracking_id = False
            return _envelope(
                intent="order_not_found_ask_review_another",
                next_expected="review_another",
                tracking_id=tracking_id,
            )

    # Step 2. Sequential flow when no new tracking ID is provided
    # Ask for tracking ID if this is the first request or after saying yes to review another
    if not _SESSION.tracking_id or _SESSION.awaiting_tracking_id:
        _SESSION.awaiting_tracking_id = True
        return _envelope(
            intent="request_tracking_id",
            next_expected="tracking_id",
        )

    # Step 6. Not delivered branch including follow-up and retry flow
    if _SESSION.order_status != "delivered":
        if _SESSION.awaiting_review_another:
            # If user types a tracking ID here, treat it as an implicit "yes"
            new_tid = _extract_tracking_id(text or "")
            if new_tid:
                _SESSION.awaiting_review_another = False
                _SESSION.awaiting_tracking_id = False
                order = get_order_by_tracking(new_tid)
                if order:
                    _SESSION.tracking_id = str(order.get("tracking_id"))
                    _SESSION.order_status = (order.get("status") or "").strip().lower()
                    _SESSION.last_order_items = [str(it.get("name", "")).strip() for it in order.get("items", [])]
                    _SESSION.delivered_at = (order.get("delivered_at") or "").strip() or None
                    _SESSION.last_order = order
                    items_detail = _items_detail_from_order(order)
                    if _SESSION.order_status == "delivered":
                        return _envelope(
                            intent="present_order_delivered_ask_return_intent",
                            next_expected="return_intent",
                            items=_SESSION.last_order_items,
                            items_detail=items_detail,
                            order_status=_SESSION.order_status,
                        )
                    else:
                        _SESSION.awaiting_review_another = True
                        return _envelope(
                            intent="present_order_not_delivered_ask_review_another",
                            next_expected="review_another",
                            items=_SESSION.last_order_items,
                            items_detail=items_detail,
                            order_status=_SESSION.order_status,
                        )
                else:
                    _SESSION.tracking_id = None
                    _SESSION.awaiting_review_another = True
                    _SESSION.awaiting_tracking_id = False
                    return _envelope(
                        intent="order_not_found_ask_review_another",
                        next_expected="review_another",
                        tracking_id=new_tid,
                    )

            if _affirms(text) or _mentions_review_another(text):
                _SESSION.awaiting_review_another = False
                _SESSION.awaiting_tracking_id = True
                return _envelope(
                    intent="request_tracking_id",
                    next_expected="tracking_id",
                )
            elif _declines(text):
                _SESSION.awaiting_review_another = False
                return _envelope(
                    intent="farewell",
                    end_session=True,
                )
            else:
                return _envelope(
                    intent="ask_review_another",
                    next_expected="review_another",
                )

        # Default defensive case to keep the dialog aligned
        _SESSION.awaiting_review_another = True
        return _envelope(
            intent="ask_review_another",
            next_expected="review_another",
        )

    # Step 5. Delivered branch with item selection and validation
    # Handle item return process for delivered orders
    if _SESSION.awaiting_review_another:
        # If user types a tracking ID here, treat it as an implicit "yes"
        new_tid = _extract_tracking_id(text or "")
        if new_tid:
            _SESSION.awaiting_review_another = False
            _SESSION.awaiting_tracking_id = False
            order = get_order_by_tracking(new_tid)
            if order:
                _SESSION.tracking_id = str(order.get("tracking_id"))
                _SESSION.order_status = (order.get("status") or "").strip().lower()
                _SESSION.last_order_items = [str(it.get("name", "")).strip() for it in order.get("items", [])]
                _SESSION.delivered_at = (order.get("delivered_at") or "").strip() or None
                _SESSION.last_order = order
                items_detail = _items_detail_from_order(order)
                if _SESSION.order_status == "delivered":
                    return _envelope(
                        intent="present_order_delivered_ask_return_intent",
                        next_expected="return_intent",
                        items=_SESSION.last_order_items,
                        items_detail=items_detail,
                        order_status=_SESSION.order_status,
                    )
                else:
                    _SESSION.awaiting_review_another = True
                    return _envelope(
                        intent="present_order_not_delivered_ask_review_another",
                        next_expected="review_another",
                        items=_SESSION.last_order_items,
                        items_detail=items_detail,
                        order_status=_SESSION.order_status,
                    )
            else:
                _SESSION.tracking_id = None
                _SESSION.awaiting_review_another = True
                _SESSION.awaiting_tracking_id = False
                return _envelope(
                    intent="order_not_found_ask_review_another",
                    next_expected="review_another",
                    tracking_id=new_tid,
                )

        if _affirms(text) or _mentions_review_another(text):
            _SESSION.awaiting_review_another = False
            _SESSION.awaiting_tracking_id = True
            return _envelope(
                intent="request_tracking_id",
                next_expected="tracking_id",
            )
        elif _declines(text):
            _SESSION.awaiting_review_another = False
            return _envelope(
                intent="farewell",
                end_session=True,
            )
        else:
            return _envelope(
                intent="ask_review_another",
                next_expected="review_another",
            )

    # Step 4.a. Await item selection for return
    if _SESSION.awaiting_items_selection:
        requested = _normalize_list_from_text(text)
        matched = _match_requested_to_order_items(requested, _SESSION.last_order_items)

        if not matched:
            return _envelope(
                intent="ask_items_to_return_retry",
                next_expected="return_items",
                items=_SESSION.last_order_items,
                requested_items=requested,
            )

        catalog_map = get_catalog_map()
        results = _validate_return_items(matched, _SESSION.delivered_at, catalog_map)
        _SESSION.last_requested_items = matched

        any_ok = any(r["eligible"] for r in results)

        # If at least one is eligible, ask to proceed. It applies only to eligible ones
        if any_ok:
            _SESSION.awaiting_items_selection = False
            _SESSION.awaiting_confirm_proceed = True
            message = _format_validation_confirmation(
                matched,
                results,
                _SESSION.lang,
            )
            return _envelope(
                intent="show_validation_and_ask_proceed",
                next_expected="confirm_proceed",
                items=_SESSION.last_order_items,
                requested_items=matched,
                return_validation=results,
                user_message=message,
                nlg=False,
            )
        else:
            _SESSION.awaiting_items_selection = False
            _SESSION.awaiting_review_another = True
            payload: Dict[str, Any] = {}
            if _SESSION.last_order:
                payload = _format_order_payload(_SESSION.last_order)
                payload["items_detail"] = _items_detail_from_order(_SESSION.last_order)
            items_detail = payload.get("items_detail", [])
            message = _format_no_eligible_message(
                payload.get("order", {}),
                items_detail,
                results,
                _SESSION.lang,
            )
            return _envelope(
                intent="show_validation_none_eligible_ask_review_another",
                next_expected="review_another",
                requested_items=matched,
                return_validation=results,
                user_message=message,
                nlg=False,
                **payload,
            )

    # Step 4.b. Await confirmation to proceed after validation
    if _SESSION.awaiting_confirm_proceed:
        if _affirms(text):
            _SESSION.awaiting_confirm_proceed = False
            _SESSION.awaiting_review_another = True

            # Retrieve and obfuscate customer email for privacy
            cust_email = None
            if _SESSION.last_order and isinstance(_SESSION.last_order.get("customer"), dict):
                cust_email = _SESSION.last_order["customer"].get("email")
            masked = _mask_email(cust_email or "")

            # Return deterministic envelope with masked email
            return _envelope(
                intent="confirm_proceed_and_ask_review_another",
                next_expected="review_another",
                requested_items=_SESSION.last_requested_items,
                masked_email=masked,
            )
        elif _declines(text):
            _SESSION.awaiting_confirm_proceed = False
            _SESSION.awaiting_review_another = True
            return _envelope(
                intent="decline_proceed_and_ask_review_another",
                next_expected="review_another",
                requested_items=_SESSION.last_requested_items,
            )
        else:
            return _envelope(
                intent="ask_proceed_retry",
                next_expected="confirm_proceed",
                requested_items=_SESSION.last_requested_items,
            )

    # Step 3. Initial decision after order delivery
    # Ask whether the user wants to return an item or not
    if _mentions_return_intent(text) or _affirms(text):
        _SESSION.awaiting_items_selection = True
        return _envelope(
            intent="ask_items_to_return",
            next_expected="return_items",
            items=_SESSION.last_order_items,
        )
    elif _declines(text):
        _SESSION.awaiting_review_another = True
        return _envelope(
            intent="decline_return_ask_review_another",
            next_expected="review_another",
        )

    # Default case asking again for return intent
    return _envelope(
        intent="ask_return_intent",
        next_expected="return_intent",
    )
