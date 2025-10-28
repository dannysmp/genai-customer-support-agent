"""
UI Service
==========================================

Overview
--------
Interactive chat interface built with Streamlit for the Customer Support Agent.
It provides a clean, responsive frontend for real-time conversations, displaying dialogue 
turns seamlessly between the customer and the service agent.

Scope
-----
1) Manage chat sessions and maintain conversation history per browser tab.
2) Display messages in an intuitive chat layout with real-time updates.
3) Handle initial assistant greeting, user input, and inactivity timeout.
4) Ensure a consistent and professional interaction flow aligned with backend logic.

Design Principles
-----------------
- Stateless communication: UI manages local state, backend determines responses.
- Minimal interface focused on clarity and message continuity.
- Automatic inactivity handling for session hygiene.
- Clean separation of configuration, state management, and rendering.

Runtime Contract
----------------
The UI communicates with the backend through standard REST endpoints:

    POST /chat
        Request:  { "prompt": "<string>" }
        Response: {
            "user_message": "<assistant reply>",
            "end_session":  <bool>
        }

    GET /health
        Response: { "ok": true, "message": "healthy" }

If `end_session` is true, the interface disables further input and displays
a closing message.

Usage
-----
    streamlit run app.py

Environment Variables
---------------------
    BACKEND_BASE_URL : Base URL of the backend API (default: http://localhost:8000)

Notes
-----
- Each Streamlit session is independent and stored in browser memory.
- The interface automatically ends the session after 60 seconds of inactivity.
"""

# -----------------------------------------------------------------------------
# Libraries
# -----------------------------------------------------------------------------

# Standard libraries
import os                                          # Environment variables and path handling
import json                                        # Safe serialization of HTTP payloads for debug and errors
import time                                        # Session inactivity tracking and time-based UI behaviors
from typing import Dict, Any                       # Precise typing for HTTP responses and session state

# Third-party libraries
import requests                                    # Synchronous HTTP client for calling the backend API
import streamlit as st                             # Streamlit UI primitives for chat rendering and state
from streamlit_autorefresh import st_autorefresh   # Lightweight timer to implement inactivity checks

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

# Define the maximum inactivity duration (in seconds) before session closes automatically
TIMEOUT_SECS = 60  

def _default_backend_base() -> str:
    """
    Resolve the backend base URL used for API communication.

    Behavior
    --------
    1. Attempts to read the BACKEND_BASE_URL environment variable.
    2. Defaults to 'http://localhost:8000' when unset.
    3. Strips trailing slashes for consistent concatenation with endpoint paths.

    Returns
    -------
    str
        Normalized base URL for the backend API.
    """
    return os.getenv("BACKEND_BASE_URL", "http://localhost:8000").rstrip("/")

# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------

def post_chat(base_url: str, text: str, timeout: float = 20.0) -> Dict[str, Any]:
    """
    Send a message to the backend API and normalize the response structure.

    Parameters
    ----------
    base_url : str
        Root URL of the backend API.
    text : str
        User input text or empty string (used for initial assistant bootstrap).
    timeout : float, optional
        Request timeout in seconds (default: 20.0).

    Returns
    -------
    Dict[str, Any]
        {
            "ok": bool,               # True if HTTP status 200–299
            "user_message": str,      # Assistant reply for UI rendering
            "end_session": bool,      # True when conversation is terminated by backend
            "raw": dict               # Full raw JSON response or error payload
        }

    Notes
    -----
    - Ensures all backend errors return a safe, human-readable fallback message.
    - Used in both initial bootstrap and regular chat turns.
    """
    url = f"{base_url}/chat"
    try:
        resp = requests.post(url, json={"prompt": text}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return {
            "ok": True,
            "user_message": str(data.get("user_message", "")).strip(),
            "end_session": bool(data.get("end_session", False)),
            "raw": data,
        }
    except Exception as e:
        return {
            "ok": False,
            "user_message": f"Connection error: {str(e)[:150]}",
            "end_session": False,
            "raw": {"error": str(e)},
        }


def get_health(base_url: str, timeout: float = 5.0) -> Dict[str, Any]:
    """
    Perform a simple health check on the backend API.

    Parameters
    ----------
    base_url : str
        Root URL of the backend API.
    timeout : float, optional
        Timeout in seconds for the GET request (default: 5.0).

    Returns
    -------
    Dict[str, Any]
        {
            "ok": bool,     # True if health endpoint is reachable and returns a positive signal
            "raw": dict     # Raw JSON response or captured error details
        }

    Notes
    -----
    - Provides quick feedback to the user via the sidebar “Health check” button.
    - Used to verify backend availability before attempting a chat interaction.
    """
    try:
        resp = requests.get(f"{base_url}/health", timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return {"ok": bool(data.get("ok", True)), "raw": data}
    except Exception as e:
        return {"ok": False, "raw": {"error": str(e)}}


def post_reset(base_url: str, timeout: float = 5.0) -> Dict[str, Any]:
    """
    Ask the backend to clear its in-memory conversation state so the next /chat
    starts a fresh session.
    """
    try:
        resp = requests.post(f"{base_url}/reset", timeout=timeout)
        resp.raise_for_status()
        return {"ok": True, "raw": resp.json()}
    except Exception as e:
        return {"ok": False, "raw": {"error": str(e)}}


def touch_activity() -> None:
    """
    Update the timestamp of the last user activity in session state.

    Behavior
    --------
    - Records the current time as `st.session_state.last_activity`.
    - Used by the inactivity watchdog to automatically close idle sessions.
    """
    st.session_state.last_activity = time.time()

# -----------------------------------------------------------------------------
# Streamlit Configuration
# -----------------------------------------------------------------------------

st.set_page_config(
    page_title="EcoMarket Customer Support",   # Browser tab title
    page_icon="🛒",                            # Tab icon for visual identity
    layout="centered",                         # Centered column layout for compact readability
    initial_sidebar_state="expanded",          # Keep sidebar open at startup for controls
)

# -----------------------------------------------------------------------------
# Sidebar Controls
# -----------------------------------------------------------------------------

# Sidebar header for runtime configuration controls
st.sidebar.title("EcoMarket • Settings")

# Editable backend URL for flexible deployment (local or remote)
backend_base = st.sidebar.text_input(
    "Backend base URL",
    value=_default_backend_base(),
    help="Root URL of the backend API used to process chat interactions.",
)

# Create two columns for aligned control buttons
col_a, col_b = st.sidebar.columns(2)
with col_a:
    # Ping API connectivity
    ping = st.button("Health check", use_container_width=True)
with col_b:
    # Clear local chat state
    reset_chat = st.button("Reset chat", type="secondary", use_container_width=True)

# Perform on-demand health verification
if ping:
    result = get_health(backend_base)
    if result["ok"]:
        st.sidebar.success("Backend API is reachable and healthy.")
    else:
        st.sidebar.error(f"Health check failed: {json.dumps(result['raw'])[:160]}")

# -----------------------------------------------------------------------------
# Session State Initialization
# -----------------------------------------------------------------------------

if "messages" not in st.session_state:
    # Sequential message log for rendering
    st.session_state.messages = []
if "bootstrapped" not in st.session_state:
    # Indicates if the assistant’s initial turn was triggered
    st.session_state.bootstrapped = False
if "ended" not in st.session_state:
    # Tracks whether the backend closed the conversation
    st.session_state.ended = False  
if "backend_base" not in st.session_state:
    # Current backend API base URL
    st.session_state.backend_base = backend_base
if "last_activity" not in st.session_state:
    # Initialize activity timestamp
    touch_activity()
if "waiting" not in st.session_state:
    # True while a request is being processed
    st.session_state.waiting = False
if "pending_text" not in st.session_state:
    # Last message sent to the backend
    st.session_state.pending_text = None

# Propagate live backend URL updates into session state dynamically
if backend_base != st.session_state.backend_base:
    st.session_state.backend_base = backend_base

# Manual reset clears both backend and UI state and refreshes the interface
if reset_chat:
    post_reset(backend_base)
    st.session_state.messages.clear()
    st.session_state.bootstrapped = False
    st.session_state.ended = False
    st.session_state.waiting = False
    st.session_state.pending_text = None
    touch_activity()
    st.toast("Chat reset successfully.", icon="🧹")
    st.rerun()

# -----------------------------------------------------------------------------
# Global Heartbeat
# -----------------------------------------------------------------------------

# Defines the periodic UI refresh interval in milliseconds to keep it active and updated
HEARTBEAT_MS = 3000

# Run autorefresh only when there is no in-flight request to the backend.
# This prevents mid-request reruns that interrupt the assistant spinner/render.
if not st.session_state.get("waiting", False):
    _ = st_autorefresh(interval=HEARTBEAT_MS, limit=0, key="ui_heartbeat")

# -----------------------------------------------------------------------------
# UI Header
# -----------------------------------------------------------------------------
# Main UI title
st.title("EcoMarket’s Customer Support Agent")

# Subtitle tagline
st.caption("Interactive AI assistant for EcoMarket’s support portal")

# First-time session banner
if not st.session_state.messages:
    st.info("Welcome to EcoMarket’s Customer Support Agent", icon="🤖")

# -----------------------------------------------------------------------------
# Chat Session Controls
# -----------------------------------------------------------------------------

# CTA to explicitly start a brand-new conversation on demand
new_chat = st.button("Start new chat", use_container_width=True)

if new_chat:
    # Request backend to reset its server-side session
    post_reset(st.session_state.backend_base)

    # Clear all UI-level conversation state
    st.session_state.messages.clear()
    st.session_state.bootstrapped = False
    st.session_state.ended = False
    st.session_state.waiting = False
    st.session_state.pending_text = None

    # Update activity timestamp and force immediate UI refresh
    touch_activity()
    st.rerun()

# -----------------------------------------------------------------------------
# Bootstrap
# -----------------------------------------------------------------------------

# Kick off the conversation with an empty turn so the backend sends its opener
if not st.session_state.bootstrapped:
    # Mark as bootstrapped first to avoid duplicate initial calls on reruns
    st.session_state.bootstrapped = True

    resp = post_chat(st.session_state.backend_base, "")

    if not resp["ok"]:
        st.toast("Backend unreachable. Check the base URL.", icon="⚠️")
        # Allow retry on next render
        st.session_state.bootstrapped = False
        st.stop()

    # Prefer server transcript if available
    transcript = resp["raw"].get("transcript")
    if isinstance(transcript, list) and transcript:
        st.session_state.messages = transcript
    else:
        msg = resp["user_message"] or "Assistant is ready."
        st.session_state.messages = [{"role": "assistant", "content": msg}]

    st.session_state.ended = resp.get("end_session", False)
    touch_activity()
    st.rerun()

# -----------------------------------------------------------------------------
# Chat History
# -----------------------------------------------------------------------------
# Render the transcript stored in session state
for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

# -----------------------------------------------------------------------------
# Inactivity watchdog
# -----------------------------------------------------------------------------

# Auto-refresh the UI and close the session after TIMEOUT_SECS with no activity
if not st.session_state.ended and not st.session_state.waiting:
    idle_time = time.time() - st.session_state.get("last_activity", 0)
    if idle_time >= TIMEOUT_SECS:
        msg = "This session was closed due to inactivity of about one minute."
        st.session_state.messages.append({"role": "assistant", "content": msg})
        with st.chat_message("assistant"):
            st.markdown(msg)

        # Reset server-side memory so the next turn starts fresh
        post_reset(st.session_state.backend_base)

        st.session_state.ended = True
        st.toast("Session closed due to inactivity", icon="⏱️")
        st.rerun()

# -----------------------------------------------------------------------------
# Chat Composer
# -----------------------------------------------------------------------------

# If the session is closed, show a warning message at the bottom of the chat 
# to indicate it has reached its final state after the assistant ended the conversation
if st.session_state.ended:
    st.warning("This session is closed. Reset the chat to start a new one.", icon="🔒")

# Phase 2: Handle the pending user request after the rerun that triggered the backend call

# Continue only if the interface is waiting for a response and a user message is pending for processing
if st.session_state.get("waiting", False) and st.session_state.get("pending_text") is not None:
    # Render a spinner while the synchronous call is in-flight
    with st.chat_message("assistant"):
        with st.spinner("Working..."):
            resp = post_chat(st.session_state.backend_base, st.session_state.pending_text)

    # Clear in-flight flags
    st.session_state.pending_text = None
    st.session_state.waiting = False

    # Error path
    if not resp["ok"]:
        err = resp["user_message"] or "Connection error."
        st.session_state.messages.append({"role": "assistant", "content": err})
        st.toast("Backend request failed", icon="⚠️")

    # Success path: backend transcript is the source of truth
    else:
        transcript = resp["raw"].get("transcript")
        if isinstance(transcript, list) and transcript:
            st.session_state.messages = transcript
        else:
            assistant_text = resp["user_message"] or "…"
            st.session_state.messages.append({"role": "assistant", "content": assistant_text})
            
    # Check for session end regardless of success or error
    if resp.get("end_session", False):
        st.session_state.ended = True
        st.toast("Session ended by assistant", icon="🛑")
        
    # Final rerun to render the assistant reply and set the final input state
    st.rerun()

# Phase 1: Capture user input and schedule processing

# Determine if the input field should be disabled.
input_disabled = st.session_state.ended or st.session_state.get("waiting", False)

# Pass the 'disabled' state to st.chat_input
prompt = st.chat_input("Type your message", disabled=input_disabled)

# Process prompt only if valid, not waiting, and session is not ended.
if prompt and prompt.strip() and not st.session_state.get("waiting", False) and not st.session_state.ended:
    # Mark in-flight and store the text
    st.session_state.waiting = True
    st.session_state.pending_text = prompt.strip()
    touch_activity()

    # Persist the user message so it renders immediately on next rerun
    st.session_state.messages.append({"role": "user", "content": st.session_state.pending_text})

    # Rerun now to show the user bubble, disable input, and enter Phase 2
    st.rerun()