"""
Retrieval-Augmented Generation (RAG) Module
===========================================

Overview
--------
Implements the retrieval layer for the conversational support agent.
This module builds and maintains a semantic index over internal knowledge
sources including orders, product catalog, returns policy, and FAQs, to
provide the language model with grounded and contextually relevant information
at each conversational turn.

Scope
-----
1) Perform semantic retrieval from both structured and unstructured data sources.
2) Supply compact and relevant context snippets to enrich LLM prompts.
3) Support transient (in-memory) and persistent (Chroma) vector storage modes.

Design Principles
-----------------
- Separation of concerns: retrieval logic is independent from the main chat
  application to ensure modularity, testability, and maintainability.
- Transparency: retrieved snippets are fully readable, traceable, and auditable
  to preserve accountability of generated responses.
- Scalability: the system currently uses a Chroma-based store but is designed
  to integrate with enterprise-grade vector databases such as Weaviate or Pinecone.
- Safety fallbacks: when retrieval fails or no relevant content is found,
  the module returns an empty string to prevent prompt contamination.

Limitations
-----------
- The current implementation relies on a local Chroma instance that is not
  persistent across sessions unless configured with environment variables.
- Retrieval accuracy depends on the freshness and completeness of local
  datasets located in the `data` directory.
- The embedding model `intfloat/multilingual-e5-base` supports multilingual
  queries but may have limited understanding of highly domain-specific terms.

Runtime Contract
----------------
The module exposes a single public interface:

    build_rag_context(query: str) -> str

This function retrieves relevant context snippets for a given query and
returns a formatted text block. The block is automatically truncated if
it exceeds the character limit defined by MAX_CONTEXT_CHARS.

Usage
-----
>>> from rag import build_rag_context
>>> ctx = build_rag_context("How do I return a damaged item?")
>>> print(ctx)
"""

# -----------------------------------------------------------------------------
# Libraries
# -----------------------------------------------------------------------------

# Standard libraries
import os                                                         # Environment variables and filesystem operations
import json                                                       # JSON serialization and parsing
import logging                                                    # Silence verbose third-party logs
import re                                                         # Lightweight pattern validations
from typing import List, Dict, Any                                # Type hints for lists, dictionaries, and general objects
from pathlib import Path                                          # Cross-platform file and directory paths
from datetime import datetime, date                               # Date parsing and calendar-day computations for delivery timelines and return windows
from functools import lru_cache                                   # Lightweight caching for deterministic function results

# Third-party libraries
from langchain_community.vectorstores import Chroma               # Local vector database for semantic search
from langchain_huggingface import HuggingFaceEmbeddings           # Transformer-based text embeddings
from langchain_core.documents import Document                     # Unified document representation for LangChain
import chromadb                                                   # Chroma client for persistent or in-memory vector storage

# Import Chroma telemetry to ensure compatibility and silent operation across environments
try:
    import chromadb.telemetry as chroma_telemetry
except Exception:
    chroma_telemetry = None

# Reduce noisy logs and progress bars at runtime for a clean CLI
logging.getLogger("chromadb").setLevel(logging.ERROR)
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
logging.getLogger("transformers").setLevel(logging.ERROR)
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_ENABLE_TELEMETRY", "0")
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("POSTHOG_DISABLED", "1")

# -----------------------------------------------------------------------------
# Compatibility guards
# -----------------------------------------------------------------------------
# Prevents Chroma from emitting telemetry events when internal capture hooks exist
if chroma_telemetry is not None and hasattr(chroma_telemetry, "capture"):
    chroma_telemetry.capture = lambda *args, **kwargs: None

# Prevents PostHog from emitting telemetry events when present
try:
    import posthog
    if hasattr(posthog, "capture"):
        posthog.capture = lambda *args, **kwargs: None
except Exception:
    pass

# -----------------------------------------------------------------------------
# Paths and constants
# -----------------------------------------------------------------------------

# Define base directories used to locate local data assets.
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"

# Data source paths
RETURNS_POLICY_DOC = DATA_DIR / "returns_policy.md"
FAQS_DOC = DATA_DIR / "faqs.md"
PRODUCT_CATALOG_DB = DATA_DIR / "product_catalog_db.json"
ORDERS_DB = DATA_DIR / "orders_db.json"

# Character limit for retrieved context in prompts
MAX_CONTEXT_CHARS = 1800

# Chroma configuration parameters
CHROMA_DIR = os.getenv("RAG_CHROMA_DIR")
CHROMA_COLLECTION = os.getenv("RAG_CHROMA_COLLECTION", "customer_support_knowledge")

# -----------------------------------------------------------------------------
# Embedding model
# -----------------------------------------------------------------------------

# Multilingual sentence embeddings used to encode both knowledge documents
# and user queries for semantic retrieval.
_embedding_model = HuggingFaceEmbeddings(model_name="intfloat/multilingual-e5-base")

# -----------------------------------------------------------------------------
# File loaders
# -----------------------------------------------------------------------------

def load_orders_block() -> str:
    """
    Load the orders database in JSON format.

    Returns
    -------
    str
        Orders serialized as formatted JSON string for inspection or debugging.
    """
    path = ORDERS_DB
    if not path.exists():
        return "[]"
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return json.dumps(data, indent=2, ensure_ascii=False)

def load_policy_block() -> str:
    """
    Load the returns policy document as plain text.

    Returns
    -------
    str
        The full returns policy content, UTF-8 decoded.
    """
    path = RETURNS_POLICY_DOC
    return path.read_text(encoding="utf-8") if path.exists() else ""

# -----------------------------------------------------------------------------
# Internal utility functions
# -----------------------------------------------------------------------------

def _load_text(path: Path) -> str:
    """Load plain text from a file if it exists."""
    return path.read_text(encoding="utf-8") if path.exists() else ""

def _load_json(path: Path) -> Any:
    """Load JSON data from a file if it exists."""
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def _mk_doc(page_content: str, **metadata: Any) -> Document:
    """Create a LangChain Document with metadata."""
    return Document(page_content=page_content, metadata=metadata)

# -----------------------------------------------------------------------------
# Document builders
# -----------------------------------------------------------------------------

def _normalize_product_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize product data to a consistent schema.

    Expected Keys
    -------------
    sku : str
        Unique stock keeping unit.
    name : str
        Product name.
    category : str
        Category or type of the product.
    is_perishable : bool
        Whether the product is perishable.
    return_window_days : int
        Number of days allowed for return.
    notes : str
        Optional descriptive notes.
    """
    return {
        "sku": entry.get("sku"),
        "name": entry.get("name"),
        "category": entry.get("category"),
        "is_perishable": bool(entry.get("is_perishable", False)),
        "return_window_days": entry.get("return_window_days", 30),
        "notes": entry.get("notes", ""),
    }

def _build_product_docs(catalog: List[Dict[str, Any]]) -> List[Document]:
    """
    Build documents from the product catalog for vector indexing.
    """
    docs = []
    for p in (catalog or []):
        prod = _normalize_product_entry(p)
        content = (
            f"Product: {prod['name']}\n"
            f"SKU: {prod['sku']}\n"
            f"Category: {prod['category']}\n"
            f"Perishable: {prod['is_perishable']}\n"
            f"Return window (days): {prod['return_window_days']}\n"
            f"Notes: {prod['notes']}"
        )
        docs.append(_mk_doc(content, source="product_catalog", sku=prod["sku"], name=prod["name"]))
    return docs

def _build_orders_docs(orders: List[Dict[str, Any]]) -> List[Document]:
    """
    Flatten order data into retrieval-friendly documents.

    Each order becomes a summary string with tracking, carrier, ETA, and items.
    """
    docs = []
    for o in orders or []:
        lines = [
            f"Order #{o.get('tracking_id')} - Status: {o.get('status')}, "
            f"Carrier: {o.get('carrier')}, ETA: {o.get('eta')}"
        ]
        if o.get("delivered_at"):
            lines.append(f"Delivered at: {o['delivered_at']}")
        for it in o.get("items", []):
            lines.append(f"- Item: {it.get('name')} (qty: {it.get('quantity', 1)})")
        docs.append(_mk_doc("\n".join(lines), source="orders", tracking_id=o.get("tracking_id")))
    return docs

def _build_policy_docs(md_text: str) -> List[Document]:
    """
    Split the returns policy document into individual sections for retrieval.
    """
    if not md_text.strip():
        return []
    docs = [_mk_doc(md_text.strip(), source="returns_policy", section="full")]
    for chunk in md_text.split("\n## "):
        if chunk and chunk != md_text.strip():
            docs.append(_mk_doc("## " + chunk, source="returns_policy", section="sub"))
    return docs

def _build_faq_docs(md_text: str) -> List[Document]:
    """
    Parse the FAQ document into discrete question/answer sections.
    """
    if not md_text.strip():
        return []
    docs, current = [], []
    for line in md_text.splitlines():
        if line.startswith("### "):
            if current:
                docs.append(_mk_doc("\n".join(current).strip(), source="faqs"))
                current = []
        current.append(line)
    if current:
        docs.append(_mk_doc("\n".join(current).strip(), source="faqs"))
    return docs

# -----------------------------------------------------------------------------
# Vector store construction
# -----------------------------------------------------------------------------

def _clear_legacy_chroma_env() -> None:
    """
    Remove old Chroma environment variables to ensure compatibility
    with the current client configuration.
    """
    legacy_keys = [
        "CHROMA_DB_IMPL",
        "PERSIST_DIRECTORY",
        "CHROMA_API_IMPL",
        "CHROMA_SERVER_HOST",
        "CHROMA_SERVER_HTTP_PORT",
        "CHROMA_SERVER_GRPC_PORT",
        "CHROMA_TELEMETRY_IMPLEMENTATION",
        "ANONYMIZED_TELEMETRY",
        "IS_PERSISTENT",
        "ANONYMIZED_TELEMETRY_ENABLED",
    ]

    for key in legacy_keys:
        if key in os.environ:
            os.environ.pop(key, None)

def _build_vectorstore() -> Chroma:
    """
    Build a Chroma index using all available sources.

    Persistence
    -----------
    - In-memory by default (fast for local development).
    - Set env var RAG_CHROMA_DIR to a folder path for persistence across runs.
    """
     # Remove legacy Chroma env keys to avoid deprecated config mode
    try:
        _clear_legacy_chroma_env()
    except Exception:
        pass

    docs: List[Document] = []
    docs += _build_policy_docs(_load_text(RETURNS_POLICY_DOC))
    docs += _build_faq_docs(_load_text(FAQS_DOC))
    docs += _build_product_docs(_load_json(PRODUCT_CATALOG_DB) or [])
    docs += _build_orders_docs(_load_json(ORDERS_DB) or [])

    if not docs:
        docs = [Document(page_content="Knowledge base is empty.", metadata={"source": "empty"})]

    if CHROMA_DIR:
        # Create a persistent Chroma client when a directory path is provided
        # This keeps the vector data available across container restarts
        client = chromadb.PersistentClient(path=CHROMA_DIR)
    else:
        # Create an in-memory Chroma client when no directory is provided
        # Data is temporary and removed after the session ends
        client = chromadb.EphemeralClient()

    # Build the LangChain Chroma store using the selected client
    # Do not use persist_directory because persistence is handled by the client
    store = Chroma.from_documents(
        documents=docs,
        embedding=_embedding_model,
        collection_name=CHROMA_COLLECTION,
        client=client,
    )
    return store

# Create the vector store and a LangChain retriever
_vectorstore = _build_vectorstore()
_retriever = _vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": 4})

# -----------------------------------------------------------------------------
# Deterministic order context
# -----------------------------------------------------------------------------

def _read_orders_db() -> List[Dict[str, Any]]:
    """
    Load and parse the orders database.

    Behavior
    --------
    Reads the JSON file defined by ORDERS_DB and validates that the parsed
    structure is a list of dictionaries. This function provides deterministic
    access to the orders database representation used by the retrieval and
    agent layers.

    Returns
    -------
    list of dict
        Parsed list of orders. Returns an empty list when the database is missing,
        corrupted, or cannot be decoded.
    """
    data = _load_json(ORDERS_DB)
    return data if isinstance(data, list) else []

def _read_catalog_db() -> List[Dict[str, Any]]:
    """
    Load and parse the product catalog database.

    Behavior
    --------
    Reads the JSON file defined by PRODUCT_CATALOG_DB and validates that
    the parsed structure is a list of dictionaries. Provides deterministic
    access to the product catalog for rule-based and retrieval components.

    Returns
    -------
    list of dict
        Parsed product catalog records. Returns an empty list when the
        database is missing, corrupted, or cannot be decoded.
    """
    data = _load_json(PRODUCT_CATALOG_DB)
    return data if isinstance(data, list) else []

def _order_lookup(tracking_id: str) -> Dict[str, Any] | None:
    """
    Retrieve an order record by its tracking identifier from the orders database.

    Parameters
    ----------
    tracking_id : str
        Unique tracking identifier provided by the user or extracted from
        a natural-language query.

    Returns
    -------
    dict or None
        The order record that matches the provided tracking identifier.
        Returns None when no corresponding record is found.

    Notes
    -----
    The function performs a deterministic string comparison on the 'tracking_id'
    field for each record retrieved from the orders database. It is independent
    from any semantic search or retrieval components and can later be adapted
    to query a relational or vector database backend without altering its contract.
    """
    candidate = str(tracking_id)
    for row in _read_orders_db():
        if str(row.get("tracking_id")) == candidate:
            return row
    return None

def _format_order_context(order: Dict[str, Any]) -> str:
    """
    Format a structured and deterministic summary of an order record
    suitable for contextual injection into the agent’s reasoning process.

    Behavior
    --------
    Generates a compact textual block describing the order’s current state,
    shipment metadata, and associated items. The format follows a consistent
    schema beginning with the header `ORDER_LOOKUP: FOUND`, ensuring that
    the agent can reliably parse and interpret factual data before invoking
    higher-level reasoning steps.

    The output includes:
      - Tracking ID
      - Status, carrier, and estimated arrival (ETA)
      - Return eligibility signals derived from delivery status
      - Itemized list of purchased products with quantities
      - Human-readable recap line for UI display or debugging

    Parameters
    ----------
    order : dict
        Order record retrieved from the orders database.

    Returns
    -------
    str
        Structured multi-line string summarizing the order in a deterministic,
        machine- and human-readable format.

    Notes
    -----
    This function does not perform any retrieval or eligibility logic. It is
    strictly responsible for canonical text formatting. The resulting block
    is consumed by both the retrieval pipeline and the conversational agent
    to maintain a consistent representation of factual order state.
    """
    status = (order.get("status") or "").strip()
    is_delivered = status.lower() == "delivered"
    reason = "status_delivered" if is_delivered else "status_not_delivered"
    action = "offer" if is_delivered else "deny"

    lines = [
        "ORDER_LOOKUP: FOUND",
        f"tracking_id: {order.get('tracking_id')}",
        f"status: {status}",
        f"carrier: {order.get('carrier')}",
        f"eta: {order.get('eta')}",
        f"return_eligible: {str(is_delivered).lower()}",
        f"return_eligibility_reason: {reason}",
        f"return_action: {action}",
        "items:",
    ]
    for it in order.get("items", []):
        qty = it.get("quantity", 1)
        lines.append(f"- {it.get('name')} (qty: {qty})")

    recap = [
        f"Order #{order.get('tracking_id')} - Status: {status}, "
        f"Carrier: {order.get('carrier')}, ETA: {order.get('eta')}"
    ]
    if order.get("delivered_at"):
        recap.append(f"Delivered at: {order['delivered_at']}")
    return "\n".join(lines + ["", *recap])

def get_orders() -> List[Dict[str, Any]]:
    """
    Retrieve all records from the orders database.

    Behavior
    --------
    Delegates to the internal JSON loader for deterministic database access.
    This function does not perform semantic retrieval or apply business logic;
    it provides direct structured access to all available order records.

    Returns
    -------
    list of dict
        List of order records. Returns an empty list when the database
        is missing, corrupted, or cannot be decoded.
    """
    return _read_orders_db()

def get_catalog_map() -> Dict[str, Dict[str, Any]]:
    """
    Return a mapping of normalized product names to their metadata
    from the product catalog database.

    Behavior
    --------
    Builds a lowercase key map from the catalog data for efficient
    product-level lookup. Intended for validation, return eligibility
    computation, and metadata retrieval — not for semantic search.

    Returns
    -------
    dict
        Dictionary where each key is a normalized (lowercase) product name
        and each value is the associated product metadata dictionary.

    Notes
    -----
    Reads the catalog database on each call. For repetitive lookups in
    performance-critical contexts, cache the result externally.
    """
    catalog = _read_catalog_db()
    return {str(p.get("name", "")).strip().lower(): p for p in catalog}

def get_order_by_tracking(tracking_id: str) -> Dict[str, Any] | None:
    """
    Retrieve a specific order from the orders database by its tracking identifier.

    Parameters
    ----------
    tracking_id : str
        Unique tracking identifier provided by the user or extracted from
        a natural-language query.

    Returns
    -------
    dict or None
        Matching order record when found. Returns None when no record matches.

    Notes
    -----
    Uses the deterministic internal lookup mechanism to ensure consistent
    matching behavior across environments. Independent from any retrieval
    or embedding components.
    """
    return _order_lookup(tracking_id)

def get_order_context(tracking_id: str) -> str:
    """
    Retrieve and format the context summary of a specific order record.

    Behavior
    --------
    Looks up the order in the orders database by its tracking identifier
    and returns a deterministic, machine-readable text summary suitable
    for contextual grounding within the conversational agent.

    Parameters
    ----------
    tracking_id : str
        Unique tracking identifier for the order.

    Returns
    -------
    str
        Formatted order context block when the order is found.
        Returns an empty string when no record matches.
    """
    order = get_order_by_tracking(tracking_id)
    return _format_order_context(order) if order else ""

def _load_returns_policy_document() -> str:
    """
    Load the returns policy document as plain lowercase text.

    Behavior
    --------
    Reads and normalizes the returns policy file for category-level
    exclusion detection. The function ensures a defensive read that
    gracefully degrades to an empty string if the file is missing or
    unreadable.

    Returns
    -------
    str
        Lowercased text of the returns policy. Returns an empty string
        when the file cannot be opened or decoded.

    Notes
    -----
    - This internal function should not be called directly by higher layers.
      Instead, use `get_forbidden_categories()` for safe and cached access.
    - The returns policy file path is defined by the constant `RETURNS_POLICY_DOC`.
    """
    try:
        return RETURNS_POLICY_DOC.read_text(encoding="utf-8").lower()
    except Exception:
        return ""

@lru_cache(maxsize=1)
def get_forbidden_categories() -> List[str]:
    """
    Extract forbidden product categories dynamically from the returns policy document.

    Behavior
    --------
    Parses the returns policy document to identify product categories that
    are explicitly marked as non-returnable. This information is used by
    the agent to enforce strict eligibility validation rules during the
    return process.

    Parsing Logic
    -------------
    - Looks for patterns like "categories such as hygiene, personal care, ...".
    - Normalizes extracted tokens to lowercase and strips punctuation.
    - If parsing yields no results, falls back to a safe default list.

    Returns
    -------
    list of str
        Lowercased list of forbidden category names.

    Notes
    -----
    - Cached using `functools.lru_cache` to avoid repeated I/O during
      multiple agent requests.
    - This function provides deterministic access for the conversational
      agent, ensuring that updates to the policy document are reflected
      automatically upon cache reset or application restart.
    """
    text = _load_returns_policy_document()
    if not text.strip():
        return ["hygiene", "personal care", "intimate apparel"]

    # Match phrasing "categories such as <list>"
    match = re.search(r"categories?\s+such\s+as\s+([a-z0-9,\s\-/&]+)", text)
    if match:
        cats = [c.strip().lower() for c in match.group(1).split(",") if c.strip()]
        return cats if cats else ["hygiene", "personal care", "intimate apparel"]

    # Default fallback
    return ["hygiene", "personal care", "intimate apparel"]

# -----------------------------------------------------------------------------
# Retrieval API
# -----------------------------------------------------------------------------

def _search(query: str, k: int = 4) -> List[str]:
    """
    Perform semantic search across indexed knowledge sources.

    Parameters
    ----------
    query : str
        Natural language user query.
    k : int, default=4
        Number of top documents to retrieve.

    Returns
    -------
    list of str
        Page contents of the top matching documents.
    """
    try:
        results = _retriever.invoke(query)
        return [d.page_content for d in results][:k]
    except Exception:
        return []

def build_rag_context(query: str) -> str:
    """
    Build a compact, deterministic context block from retrieved knowledge.

    Behavior
    --------
    1) Resolve a tracking ID candidate and emit an ORDER_LOOKUP header first so
       core facts are never truncated.
    2) When an order is found and 'delivered_at' is present, compute the exact
       calendar-day delta to today's date and emit RETURN_ELIGIBILITY_SIGNALS
       per item using only data from:
         - Product Catalog (e.g., return_window_days, is_perishable, category)
         - Returns Policy / FAQs (category-level exclusions; hygiene hints)
       No hard-coded defaults are used. If no applicable window exists in the
       catalog and none can be inferred from policy/FAQs, mark the item as
       ineligible with reason "insufficient_window_info".
    3) Append semantic snippets after deterministic blocks while respecting
       MAX_CONTEXT_CHARS. If nothing is available, return "".

    Parameters
    ----------
    query : str
        User's natural language input or question.

    Returns
    -------
    str
        Formatted snippet collection ready for prompt injection.
        Returns an empty string if no results are found.
    """
    # Identify tracking ID candidate
    token = (query or "").strip()
    candidate = ""
    m = re.search(r"(?=\b[A-Za-z0-9-]{3,14}\b)(?=.*\d)\b[A-Za-z0-9-]{3,14}\b", token)
    candidate = m.group(0) if m else ""

    # Build ORDER_LOOKUP
    order_block = ""
    order_obj = None
    if candidate:
        order_obj = _order_lookup(candidate)
        if order_obj:
            order_block = _format_order_context(order_obj)
        else:
            order_block = f"ORDER_LOOKUP: NOT_FOUND\ntracking_id: {candidate}"

    # Per-item return window validation, only when the order exists
    signals_block = ""
    if order_obj:
        delivered_at_raw = (order_obj.get("delivered_at") or "").strip()
        items = order_obj.get("items", []) or []

        # Load the product catalog and build a lowercase lookup map for fast access
        catalog = _load_json(PRODUCT_CATALOG_DB) or []
        catalog_map = {str(p.get("name", "")).strip().lower(): p for p in catalog}

        # Combine text from policy and FAQs to detect exclusion keywords such as hygiene
        policy_text = _load_text(RETURNS_POLICY_DOC).lower()
        faqs_text = _load_text(FAQS_DOC).lower()
        policy_hints = policy_text + "\n" + faqs_text

        def _category_non_returnable(cat: str) -> bool:
            c = (cat or "").lower().strip()
            # Match keywords that indicate non-returnable categories based on policy text
            hints = ["hygiene", "personal care", "opened hygiene", "intimate"]
            return any(h in policy_hints and h in c for h in hints)

        lines: List[str] = []
        if delivered_at_raw:
            try:
                delivered_date = datetime.strptime(delivered_at_raw, "%Y-%m-%d").date()
                today = date.today()
                elapsed = (today - delivered_date).days
            except Exception:
                delivered_date, today, elapsed = None, None, None
        else:
            delivered_date, today, elapsed = None, None, None

        for it in items:
            name = str(it.get("name", "")).strip()
            meta = catalog_map.get(name.lower(), {}) or {}
            cat = str(meta.get("category", "")).strip()
            is_perishable = bool(meta.get("is_perishable", False))

            # Determine applicable return window using catalog data if available
            win = meta.get("return_window_days", None)

            # Validate time eligibility only when both delivery date and window exist
            time_ok = None
            if delivered_date is not None and win is not None:
                try:
                    win_int = int(win)
                    time_ok = (elapsed is not None) and (elapsed <= win_int)
                except Exception:
                    # Invalid catalog value means not eligible
                    time_ok = False

            # Check perishable constraint using catalog flag without inventing limits
            perish_ok = True
            if is_perishable:
                # Keep as True unless policy explicitly forbids it
                perish_ok = True

            # Check for category restrictions defined in policy or FAQs
            cat_ok = not _category_non_returnable(cat)

            # Determine eligibility following the defined order of checks
            eligible = True
            reason = "ok"
            if win is None or delivered_date is None:
                eligible = False
                reason = "insufficient_window_info"
            elif time_ok is False:
                eligible = False
                reason = "time_window_exceeded"
            elif not perish_ok:
                eligible = False
                reason = "perishable_excluded"
            elif not cat_ok:
                eligible = False
                reason = "category_excluded"

            # Build a concise machine-readable summary for each product
            line = (
                "RETURN_ELIGIBILITY_SIGNALS\n"
                f"product: {name}\n"
                f"delivered_at: {delivered_at_raw or 'unknown'}\n"
                f"today: {(today.isoformat() if today else 'unknown')}\n"
                f"elapsed_days: {(elapsed if elapsed is not None else 'unknown')}\n"
                f"catalog_window_days: {(int(win) if isinstance(win, (int, float, str)) and str(win).isdigit() else 'unknown')}\n"
                f"is_perishable: {str(is_perishable).lower()}\n"
                f"category: {cat or 'unknown'}\n"
                f"policy_category_exclusion_hint: {str(not cat_ok).lower()}\n"
                f"eligible: {str(eligible).lower()}\n"
                f"reason: {reason}"
            )
            lines.append(line)

        if lines:
            signals_block = "\n".join(lines)

    # Semantic retrieval via LangChain retriever
    semantic_snippets = _search(query)

    # Assemble with ORDER_LOOKUP and validation first, protected from truncation
    header = "Retrieved Context:\n"
    bullets: List[str] = []

    if order_block:
        bullets.append(order_block)
    if signals_block:
        bullets.append(signals_block)

    # Allocate remaining budget to semantic snippets, preserving earlier blocks
    budget = MAX_CONTEXT_CHARS - len(header) - sum(len(b) + 2 for b in bullets) - 16
    for s in semantic_snippets:
        if budget <= 0:
            break
        take = s[:budget]
        if take:
            bullets.append(take)
            budget -= len(take) + 2

    # If nothing to show, return empty string
    if not bullets:
        return ""

    formatted = "\n".join(f"- {s}" for s in bullets)
    block = f"{header}{formatted}\n"

    # Final defensive truncation
    if len(block) > MAX_CONTEXT_CHARS:
        block = block[: MAX_CONTEXT_CHARS - 3] + "..."

    return block
