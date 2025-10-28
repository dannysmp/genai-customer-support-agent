"""
Customer Support Service
==========================================

Overview
--------
Unified conversational agent executing a single interactive chat session.
Behavior, model selection, and generation parameters are defined in
prompts/settings.toml. This module handles configuration loading, prompt
rendering with RAG-provided context, LLM invocation, envelope parsing, and
console I/O.

Scope
-----
1) Order status inquiry with ETA/carrier from an in-repo orders dataset.
2) Product return guidance with eligibility checks from a returns policy.

Design Principles
-----------------
- Prompts and configuration externalized in `prompts/settings.toml`
- Grounded answers via a Retrieval-Augmented (RAG) context assembled each turn
- Deterministic-enough behavior via TOML (model/temperature)
- Strict contract where the LLM returns a JSON envelope consumed by this app

Runtime Contract
----------------
Each turn, the LLM returns a JSON object that includes at least:
- user_message (str): text to display to the customer
- end_session (bool): whether to terminate the conversation after the reply

The agent determines the dialog state and the NLG component composes the final
user-facing message.

If parsing fails, the application prints a safe fallback line and continues.

Usage
-----
    python app.py
"""

# -----------------------------------------------------------------------------
# Libraries
# -----------------------------------------------------------------------------

# Standard libraries
import os                                                # Environment variables and path handling
import json                                              # JSON serialization and parsing
import time                                              # Sleep for short backoff delays during transient errors
from dataclasses import dataclass, field                 # Lightweight state containers
from typing import Optional, List                        # Type hints for clarity and safety
from datetime import datetime                            # Timestamp labels for console I/O
import sys                                               # Std streams for non-blocking input on POSIX

# Third-party libraries
import tomli                                             # TOML parser for configuration and prompts
from dotenv import load_dotenv                           # Load environment variables
from openai import OpenAI                                # Official OpenAI Python SDK
from rich import print                                   # Styled console output for readability
from functools import lru_cache                          # Standard library decorator that caches function results in memory
from fastapi import FastAPI, HTTPException               # Web API framework and HTTP error handling
from pydantic import BaseModel                           # Data validation and schema definition
import uvicorn                                           # ASGI server for running FastAPI apps

# Local modules
from rag import build_rag_context                        # RAG integration
from agent import run as run_agent_workflow              # Agentic workflow execution using LangGraph tools
from agent import reset_session as reset_agent_session   # Server-side agent state reset

# -----------------------------------------------------------------------------
# Configuration bootstrap
# -----------------------------------------------------------------------------

# Load secrets from environment (e.g., OPENAI_API_KEY). Model params come from TOML.
load_dotenv()

API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    raise RuntimeError("OPENAI_API_KEY environment variable is required but not set.")

# OpenAI client. Model/temperature are read from TOML at call time.
client = OpenAI(api_key=API_KEY)

# Resolve project-relative paths
ROOT = os.path.dirname(__file__)
DATA_DIR = os.path.join(ROOT, "data")
TOML_PATH = os.path.join(ROOT, "prompts", "settings.toml")

# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------

def timestamp_str() -> str:
    """
    Build a stable, human-readable timestamp label for console I/O.

    Purpose
    -------
    Generate a date-time string to annotate each printed chat line so it is
    auditable and easy to follow in transcripts and logs.

    Format
    ------
    'YYYY-MM-DD HH:MM:SS' in local time.

    Returns
    -------
    str
        Current local timestamp formatted as 'YYYY-MM-DD HH:MM:SS'.
    """
    # Use strftime to format the current local time for console output.
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def read_input_with_timeout(prompt_text: str, timeout_seconds: int = 60) -> Optional[str]:
    """
    Read one console line with a hard timeout

    Behavior
    waits up to timeout_seconds for a single line of user input
    returns the stripped text on success
    returns None on timeout
    """
    try:
        if os.name == "nt":
            import msvcrt
            start = time.time()
            buf = []
            print(prompt_text, end="", flush=True)
            while time.time() - start < timeout_seconds:
                if msvcrt.kbhit():
                    ch = msvcrt.getwche()
                    if ch in ("\r", "\n"):
                        print()
                        return "".join(buf).strip()
                    buf.append(ch)
                time.sleep(0.05)
            print()
            return None
        else:
            import select
            sys.stdout.write(prompt_text)
            sys.stdout.flush()
            rlist, _, _ = select.select([sys.stdin], [], [], timeout_seconds)
            if rlist:
                line = sys.stdin.readline()
                return (line or "").strip()
            return None
    except Exception:
        try:
            return input(prompt_text).strip()
        except Exception:
            return None

# -----------------------------------------------------------------------------
# Configuration loaders
# -----------------------------------------------------------------------------

def load_config() -> dict:
    """
    Load and validate the application configuration from `settings.toml`.

    Responsibilities
    ----------------
    1) Read the TOML file from TOML_PATH.
    2) Validate required sections and keys (fail fast on misconfiguration).
    3) Enforce that the selected model is in the allowed list.

    Contract
    --------
    Required keys:
      - [general]: chat_models (list), model (str), temperature (float/int)
      - [prompts]: agent_role (str), conversational_agent (str)

    Returns
    -------
    dict
        Parsed TOML as a Python dictionary with at least 'general' and 'prompts'.

    Raises
    ------
    RuntimeError
        If the file is missing required sections/keys or contains invalid values.

    Notes
    -----
    - This function centralizes config validation so callers can rely on a
      consistent and complete configuration shape.
    - Raising RuntimeError here is intentional to surface configuration issues
      immediately at startup.
    """
    # Read and parse TOML file from disk.
    with open(TOML_PATH, "rb") as f:
        cfg = tomli.load(f)

    # Validate presence of top-level sections.
    if "general" not in cfg or "prompts" not in cfg:
        raise RuntimeError("settings.toml must include [general] and [prompts] sections.")

    # Validate [general] keys: model governance and sampling parameters.
    g = cfg["general"]
    for key in ("chat_models", "model", "temperature", "max_attempts"):
        if key not in g:
            raise RuntimeError(f"settings.toml missing required key general.{key}")

    # Validate [prompts] keys: agent instructions and the main conversational template.
    p = cfg["prompts"]
    for key in ("agent_role", "conversational_agent"):
        # Must exist, be a string, and not be empty/whitespace.
        if key not in p or not isinstance(p[key], str) or not p[key].strip():
            raise RuntimeError(f"settings.toml missing required key prompts.{key}")

    # Enforce that the configured model is part of the allowed list.
    allowed = g["chat_models"]
    model = g["model"]
    if not isinstance(allowed, list) or model not in allowed:
        raise RuntimeError(f"general.model must be one of general.chat_models: {allowed}")

    # If all checks pass, return the parsed configuration.
    return cfg

@lru_cache(maxsize=1)
def _cached_config() -> dict:
    """Return cached configuration loaded once"""
    return load_config()

# -----------------------------------------------------------------------------
# Conversation state management
# -----------------------------------------------------------------------------

@dataclass
class ChatTurn:
    """
    Represent a single conversational turn.

    Attributes
    ----------
    role : str
        Either 'user' or 'assistant'. Identifies who produced the message.
    content : str
        The textual content of the message.
    """
    role: str   # 'user' or 'assistant'
    content: str

@dataclass
class ChatSession:
    """
    Maintain a rolling history of conversation turns.

    Purpose
    -------
    - Provides continuity across turns by keeping a buffer of prior exchanges.
    - Supplies a compact transcript for the LLM to inject into prompts.

    Attributes
    ----------
    history : List[ChatTurn]
        List of user and assistant turns stored in chronological order.
    """
    history: List[ChatTurn] = field(default_factory=list)

    def add(self, role: str, content: str) -> None:
        """
        Append a message to the session history.

        Parameters
        ----------
        role : str
            Either 'user' or 'assistant'.
        content : str
            Message text to record in the history.
        """
        self.history.append(ChatTurn(role=role, content=content))

    def render_history_for_prompt(self, max_turns: int = 8) -> str:
        """
        Render a compact transcript for the {{chat_history}} placeholder.

        Parameters
        ----------
        max_turns : int, default=8
            Maximum number of recent turns to include in the transcript. Acts
            as a sliding window to control token usage.

        Returns
        -------
        str
            Newline-joined transcript of the form:
            "User: <message>" / "Assistant: <message>"
        """
        window = self.history[-max_turns:]
        lines = []
        for t in window:
            prefix = "User" if t.role == "user" else "Assistant"
            lines.append(f"{prefix}: {t.content}")
        return "\n".join(lines)

# -----------------------------------------------------------------------------
# LLM interaction
# -----------------------------------------------------------------------------

def call_llm(prompt: str, general_cfg: dict, force_text: bool = False) -> str:
    """
    Send a conversational prompt to the LLM and return its response.

    Parameters
    ----------
    prompt : str
        Fully rendered prompt to send as the assistant's input.
    general_cfg : dict
        Configuration under [general] in settings.toml. Must include 'model'
        and 'temperature'.
    force_text : bool
        When True, disables JSON response mode even if the model supports it.
        Use this for NLG so the model returns plain natural language.

    Returns
    -------
    str
        Raw text content of the assistant's reply.
        If an error occurs after brief retries, a compact JSON error envelope
        is returned so the CLI can fall back gracefully.
    """
    model = general_cfg["model"]
    temperature = float(general_cfg["temperature"])

    # Retry policy for transient issues
    attempts = 0
    max_attempts = int(general_cfg["max_attempts"])

    # Backoff schedule in seconds for retries
    backoff_seconds = [0.6, 1.2]

    # Models known to support response_format={"type":"json_object"}
    json_mode_whitelist = {
        "gpt-4o",
        "gpt-4o-2024-05-13",
        "gpt-4o-2024-08-06",
        "gpt-4o-mini",
        "gpt-4o-mini-2024-07-18",
    }
    use_json_mode = (model in json_mode_whitelist) and (not force_text)

    while attempts < max_attempts:
        try:
            messages = [{"role": "user", "content": prompt}]

            if use_json_mode:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                    timeout=60,
                )
            else:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    timeout=60,
                )

            return resp.choices[0].message.content

        except Exception as err:
            attempts += 1
            if attempts < max_attempts:
                # Wait before retrying using a capped backoff schedule
                idx = min(attempts - 1, len(backoff_seconds) - 1)
                time.sleep(backoff_seconds[idx])
            else:
                # Final failure path, return a machine-readable JSON envelope
                return json.dumps({
                    "error": "llm_request_failed",
                    "message": "The model could not process the request.",
                    "details": str(err)[:200],
                    "user_message": (
                        f"Temporary issue: {str(err)[:120]}"
                        if os.getenv("LOG_LEVEL", "").upper() == "DEBUG" else ""
                    ),
                })

# -----------------------------------------------------------------------------
# JSON envelope parsing
# -----------------------------------------------------------------------------

def extract_json_or_none(raw: str) -> Optional[dict]:
    """
    Attempt to extract a JSON object from potentially noisy model output

    Purpose
    -------
    The model should always return a strict JSON envelope. In practice, responses
    may include formatting artifacts such as Markdown code fences or extra text.
    This function applies multiple parsing strategies to recover a valid JSON
    object whenever possible.

    Strategy
    --------
    1. Attempt direct json.loads
    2. Strip ```json ... ``` code fences and parse again
    3. Scan for the first balanced top-level JSON object in mixed content

    Parameters
    ----------
    raw : str
        Raw assistant text output

    Returns
    -------
    dict or None
        Parsed JSON object if successful, otherwise None
    """
    s = (raw or "").strip()

    # Try to parse directly as JSON since many responses are already valid
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Handle fenced code blocks ```json ... ```
    # Some models wrap JSON in Markdown fences, remove them and parse again
    if s.startswith("```") and s.endswith("```"):
        cleaned = s.strip("`")
        cleaned = cleaned.replace("json\n", "").strip()
        try:
            obj = json.loads(cleaned)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    # Fallback that scans the string and tries to extract the first balanced JSON object
    # This is resilient when the model adds prose before or after the JSON
    start = s.find("{")
    if start == -1:
        return None

    # Tracks nested braces { ... { ... } ... }
    depth = 0
    # Tracks whether the cursor is inside a JSON string "..."
    in_string = False
    # Tracks an escape character within a JSON string
    escape = False

    # Iterate character by character to find the end of the first balanced object
    for i in range(start, len(s)):
        ch = s[i]

        if in_string:
            # Inside a string, handle escapes and possible string termination
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        else:
            # Not inside a string, detect the start of a string or brace changes
            if ch == '"':
                in_string = True
                continue

        # Update brace depth only when not inside a string
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                # Found a complete top-level JSON object candidate
                candidate = s[start:i + 1]
                try:
                    obj = json.loads(candidate)
                    if isinstance(obj, dict):
                        return obj
                except Exception:
                    # If this candidate fails, continue scanning since there might be another
                    pass

    # No valid JSON object could be recovered
    return None

# -----------------------------------------------------------------------------
# Natural Language Generation (NLG) helpers
# -----------------------------------------------------------------------------

def build_nlg_reply(
    envelope: dict,
    user_text: str,
    chat_history: str,
) -> str:
    """
    Generate the natural language response displayed to the user.

    Overview
    --------
    This function composes the final user-facing message for each turn in the
    conversation. It relies on the agent envelope to understand the current
    dialog state, and builds a structured prompt for the LLM that produces
    coherent, grounded, and contextually appropriate replies.

    The behavior follows strict workflow rules:
    1. When the agent expects the tracking ID, it outputs a direct, fixed
       question without invoking the LLM.
    2. For every other dialog stage, it constructs a prompt containing:
       - The current envelope and context.
       - Relevant data retrieved from RAG.
       - The conversation history.
       - Policy rules that enforce a controlled and deterministic reply.

    Parameters
    ----------
    envelope : dict
        The structured message returned by the agent logic, containing
        control flags, the intent, expected slot, and any payload data.

    user_text : str
        The latest input text from the user, used to build the RAG context.

    chat_history : str
        A textual representation of the conversation so far, included in the
        model prompt for context continuity.

    Returns
    -------
    str
        The final, ready-to-display text message that the UI will show to the
        user in the correct language and aligned with the defined workflow.
    """

    # Handle the tracking ID question directly without LLM generation
    # This is the only case where a fixed prompt is enforced
    lang = (envelope or {}).get("lang") or "en"
    nxt = (envelope or {}).get("next_expected")

    def _q_tracking() -> str:
        """Return the direct tracking ID question in the correct language."""
        return (
            "¿Podrías proporcionarme el ID de seguimiento, por favor?"
            if lang == "es"
            else "Could you please provide the tracking ID?"
        )

    # If the next expected step is the tracking ID, stop and output the question immediately
    if nxt == "tracking_id" or (envelope or {}).get("intent") == "request_tracking_id":
        return _q_tracking()

    # Load configuration and model parameters required for the LLM prompt
    cfg = _cached_config()
    general_cfg = cfg["general"]
    prompts_cfg = cfg["prompts"]

    # Build the contextual RAG snippet for this turn using the user input
    rag_ctx = build_rag_context(user_text)

    # Resolve the conversational template defined in TOML
    template = prompts_cfg.get("conversational_agent", "")
    agent_role = prompts_cfg.get("agent_role", "")

    def _substitute(block: str, token: str, value: str) -> str:
        """Replace double-braced placeholders with a runtime value."""
        return block.replace(f"{{{{{token}}}}}", value)

    rendered_prompt = template
    rendered_prompt = _substitute(rendered_prompt, "agent_role", agent_role)
    rendered_prompt = _substitute(rendered_prompt, "rag_context", rag_ctx or "")
    rendered_prompt = _substitute(rendered_prompt, "chat_history", chat_history or "")
    rendered_prompt = _substitute(rendered_prompt, "user_text", user_text or "")

    # Append the live envelope so the model can follow deterministic policies
    envelope_json = json.dumps(envelope, ensure_ascii=False, indent=2)
    nlg_prompt = (
        f"{rendered_prompt.strip()}\n\n"
        "Envelope JSON:\n"
        f"{envelope_json}\n"
    )

    # Generate the model output through the LLM call
    raw = call_llm(nlg_prompt, general_cfg, force_text=True)

    # Parse structured responses if present. Otherwise return plain text
    parsed = extract_json_or_none(raw)
    if isinstance(parsed, dict) and "user_message" in parsed:
        return (str(parsed.get("user_message") or "").strip() or raw).strip()
    return raw.strip()

# -----------------------------------------------------------------------------
# Command-line interface for interactive agent chat
# -----------------------------------------------------------------------------

def run_cli_chat_session() -> None:
    """
    Execute an interactive chat session through the full agent workflow.

    Description
    -----------
    This function initializes and manages a complete conversational session with the
    EcoMarket Customer Support Agent. The workflow maintains session state through
    the agent layer and generates contextually grounded replies using the LLM when
    natural language generation is required.

    Responsibilities
    ----------------
    1. Load configuration settings and initialize the chat session.
    2. Display a fixed welcome message to introduce the assistant.
    3. Start the agent workflow with an empty input to trigger the initial dialog,
       typically the language preference prompt.
    4. Process each user message sequentially, updating the session state and
       invoking the agent workflow to determine the next intent and response.
    5. When the agent marks an envelope with `nlg=True` or omits `user_message`,
       invoke `build_nlg_reply` to synthesize the final reply text.
    6. Continue the exchange until the agent signals `end_session=True`.

    Interaction Model
    -----------------
    - The agent defines the logic and state transitions for the dialog.
    - The LLM composes human-readable responses based on the agent envelope,
      the retrieved RAG context, and the conversation history.
    - The user interacts through the console interface, receiving timestamped
      assistant outputs for each turn.

    Termination
    ------------
    The session ends automatically when:
      • The agent sets `end_session` to True.
      • The user remains inactive beyond the configured timeout.
      • The user exits manually through keyboard interruption.

    """
    session = ChatSession()

    # Display a fixed welcome message
    welcome_line = "Welcome to EcoMarket’s Customer Support Agent"
    print(f"[Agent] {timestamp_str()} : {welcome_line}")
    session.add(role="assistant", content=welcome_line)

    # Initialize the agent workflow to start the dialog with language selection
    env = run_agent_workflow("")
    msg = getattr(env, "user_message", None)
    env_dict = env.model_dump() if hasattr(env, "model_dump") else dict(env)

    if not msg or getattr(env, "nlg", None):
        history_txt = session.render_history_for_prompt()
        msg = build_nlg_reply(env_dict, user_text="", chat_history=history_txt)

    print(f"[Agent] {timestamp_str()} : {msg or 'Let me connect you with a human agent.'}")
    session.add(role="assistant", content=msg or "")

    if getattr(env, "end_session", False) is True:
        return

    # Manage the conversational loop
    while True:
        try:
            user_text = read_input_with_timeout(f"[Client] {timestamp_str()} : ", timeout_seconds=60)
            session_closed_msg = f"I am closing this session due to inactivity. If you need anything else, you can start a new chat at any time. Have a nice day."
            if user_text is None:
                print(f"[Agent] {timestamp_str()} : {session_closed_msg}")
                return
        except (EOFError, KeyboardInterrupt):
            # Allow graceful exit on Ctrl-D or Ctrl-C without stack traces
            print()
            return

        # Persist the user turn for context in subsequent prompts
        session.add(role="user", content=user_text)

        # Invoke the agent for the current user message
        env = run_agent_workflow(user_text)
        msg = getattr(env, "user_message", None)
        env_dict = env.model_dump() if hasattr(env, "model_dump") else dict(env)

        # Generate natural language output when required
        if not msg or getattr(env, "nlg", None):
            history_txt = session.render_history_for_prompt()
            msg = build_nlg_reply(env_dict, user_text, history_txt)

        # Output the assistant reply
        print(f"[Agent] {timestamp_str()} : {msg or 'Let me connect you with a human agent.'}")
        session.add(role="assistant", content=msg or "")

        # Terminate when the agent signals session closure
        if getattr(env, "end_session", False) is True:
            return

# -----------------------------------------------------------------------------
# Web API interface for interactive agent chat
# -----------------------------------------------------------------------------

# Web application instance and a single in-memory chat session
app = FastAPI(title="EcoMarket Customer Service Agent")
_WEB_SESSION = ChatSession()

class ChatIn(BaseModel):
    prompt: str

@app.get("/health")
def health() -> dict:
    """
    Health check endpoint

    Returns
    -------
    dict
        JSON object confirming that the service is running
    """
    return {"ok": True}

def _render_transcript() -> list[dict]:
    """
    Serialize the current chat session into a list of dicts suitable for the UI.
    Each item has the keys: 'role' and 'content'.
    """
    return [{"role": t.role, "content": t.content} for t in _WEB_SESSION.history]

@app.post("/chat")
def chat(req: ChatIn) -> dict:
    """
    Handle chat requests from UI clients.

    Runtime behavior
    ----------------
    This endpoint operates under a single-process single-session design.

    - A single ChatSession instance preserves the conversation history for all requests
      served by this process.
    - Each user prompt is appended to the history before the agent executes.
    - When the agent omits user_message or sets nlg=True, the NLG layer generates
      the text using the compact conversation history.
    - The assistant reply is appended to the history after generation to maintain
      continuity for subsequent turns.
    - When the agent sets end_session=True, the function returns the payload,
      clears the in-memory history, and ends the session.
    """
    try:
        # Record the user turn only when it is non-empty
        if (req.prompt or "").strip():
            _WEB_SESSION.add(role="user", content=req.prompt)

        # Run the deterministic agent workflow for this turn
        env = run_agent_workflow(req.prompt)
        msg = getattr(env, "user_message", None)
        env_dict = env.model_dump() if hasattr(env, "model_dump") else dict(env)

        # Synthesize user-facing text when the agent omits it or requires NLG
        if not msg or getattr(env, "nlg", None):
            history_txt = _WEB_SESSION.render_history_for_prompt()
            msg = build_nlg_reply(env_dict, req.prompt, chat_history=history_txt)

        # Append the assistant message to the rolling history
        _WEB_SESSION.add(role="assistant", content=msg or "")

        # If the agent closes the session, reset the in-memory history
        if getattr(env, "end_session", False) is True:
            transcript = _render_transcript()
            _WEB_SESSION.history.clear()
            payload = env.model_dump() if hasattr(env, "model_dump") else env_dict
            payload["user_message"] = msg
            payload["transcript"] = transcript
            return payload

        # Ensure the response always includes user_message
        if hasattr(env, "user_message"):
            env.user_message = msg
            transcript = _render_transcript()
            payload = env.model_dump() if hasattr(env, "model_dump") else env_dict
            payload["user_message"] = msg
            payload["transcript"] = transcript
            return payload

        # Fallback for plain dict-like outputs
        env_dict["user_message"] = msg
        env_dict["transcript"] = _render_transcript()
        return env_dict
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error {str(e)[:200]}")

@app.post("/reset")
def reset() -> dict:
    """
    Reset the server-side conversation state to initialize a new chat session.
    """
    try:
        _WEB_SESSION.history.clear()
        reset_agent_session()
        return {"ok": True, "message": "Server-side session successfully reset."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reset operation failed: {str(e)[:200]}")

# -----------------------------------------------------------------------------
# Application entrypoint
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Determine the execution interface from command-line arguments

    Examples
    --------
    python app.py --cli
        Starts the command-line interface for local interaction

    python app.py
        Starts the Web API interface for the Streamlit UI
    """
    if "--cli" in sys.argv:
        # Start the command-line interface
        run_cli_chat_session()
    else:
        # Start the Web API interface
        port = int(os.getenv("PORT", os.getenv("BACKEND_PORT", "8000")))
        uvicorn.run("app:app", host="0.0.0.0", port=port)
