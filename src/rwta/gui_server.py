"""Newline-delimited JSON-RPC stdio server for the native Mac GUI.

Protocol: each request from the client and each event from the server is a
single JSON object terminated by a newline. The Swift app spawns this module
as a subprocess and pipes stdin/stdout.

Client → server requests::

    {"id": 1, "method": "list_saves"}
    {"id": 2, "method": "detect_location"}
    {"id": 3, "method": "new_game", "params": {
        "city": "...", "region": "...", "country": "...",
        "address": "...", "latitude": 37.8, "longitude": -122.1
    }}
    {"id": 4, "method": "load_game", "params": {"name": "moraga-1217"}}
    {"id": 5, "method": "input", "params": {"text": "Walk to the park"}}
    {"id": 6, "method": "look"}
    {"id": 7, "method": "regenerate"}
    {"id": 8, "method": "save", "params": {"name": null}}
    {"id": 9, "method": "quit"}

Server → client events (no id, ``"event": ...``)::

    {"event": "ready"}
    {"event": "saves", "saves": [...]}
    {"event": "detected_location", ...}
    {"event": "loading", "message": "..."}
    {"event": "narrative", "text": "..."}
    {"event": "suggestions", "items": ["...", "...", "..."]}
    {"event": "location", "city": ..., "lat": ..., "time": ..., ...}
    {"event": "image", "data": "<base64 png>"}
    {"event": "history", "messages": [...]}
    {"event": "cost", "usd": 0.012}
    {"event": "error", "message": "..."}

Server → client responses to a request always echo ``"id"``::

    {"id": 1, "result": {...}}
    {"id": 1, "error": "message"}
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from anthropic import APIError

from rwta.config import DATA_DIR, LOCAL_TIMEZONE
from rwta.formatting import parse_suggestions
from rwta.imagegen import generate_scene_image, get_image_style, list_image_styles
from rwta.llm import GameNarrator, get_cached_weather
from rwta.location import Location, geocode_location, get_city_from_ip
from rwta.state import (
    GameState,
    ImageHistoryEntry,
    delete_save,
    find_save_by_name,
    list_saves,
    load_game,
    save_game,
)

logger = logging.getLogger(__name__)

# Lock to ensure only one writer mutates stdout at a time. Stdout is the
# wire protocol; mixing partial writes from multiple threads would corrupt it.
_stdout_lock = threading.Lock()


def _emit(obj: dict[str, Any]) -> None:
    """Write a single JSON object + newline to stdout, flushed."""
    line = json.dumps(obj, ensure_ascii=False)
    with _stdout_lock:
        sys.stdout.write(line)
        sys.stdout.write("\n")
        sys.stdout.flush()


def _send_event(event: str, **fields: Any) -> None:
    payload: dict[str, Any] = {"event": event}
    payload.update(fields)
    _emit(payload)


def _send_result(req_id: Any, result: Any) -> None:
    _emit({"id": req_id, "result": result})


def _send_error(req_id: Any, message: str) -> None:
    _emit({"id": req_id, "error": message})


def _location_to_payload(loc: Location) -> dict[str, Any]:
    return {
        "city": loc.city,
        "region": loc.region,
        "country": loc.country,
        "address": loc.address,
        "latitude": loc.latitude,
        "longitude": loc.longitude,
    }


def _state_location_payload(state: GameState) -> dict[str, Any]:
    """Build a location event payload for the current state."""
    loc = state.get_current_location()
    weather = get_cached_weather(loc)
    weather_str = str(weather) if weather else None
    return {
        "city": loc.city,
        "region": loc.region,
        "country": loc.country,
        "address": loc.address,
        "latitude": loc.latitude,
        "longitude": loc.longitude,
        "game_time": state.get_formatted_game_time(),
        "weather": weather_str,
        "save_name": state.save_name,
    }


@dataclass
class ServerSession:
    """Holds the stateful pieces of a running game session."""

    narrator: GameNarrator
    state: GameState | None = None
    fast: bool = False
    last_suggestions: list[str] = None  # type: ignore[assignment]
    image_thread: threading.Thread | None = None
    image_style_id: str = "photo"
    last_failed_input: str | None = None

    def __post_init__(self) -> None:
        if self.last_suggestions is None:
            self.last_suggestions = []


# --- Per-method handlers --------------------------------------------------


def _handle_list_saves(_session: ServerSession, _params: dict[str, Any]) -> dict[str, Any]:
    saves = list_saves()
    payload = []
    for path, name, updated in saves:
        entry: dict[str, Any] = {"name": name, "updated_at": updated, "path": str(path)}
        preview = _latest_cached_image_for_save(path)
        if preview is not None:
            entry["preview_image_path"] = preview["path"]
            entry["preview_style_name"] = preview["style_name"]
        payload.append(entry)
    return {"saves": payload}


def _handle_detect_location(_session: ServerSession, _params: dict[str, Any]) -> dict[str, Any]:
    loc = get_city_from_ip()
    return _location_to_payload(loc)


def _handle_new_game(session: ServerSession, params: dict[str, Any]) -> dict[str, Any]:
    session.image_style_id = get_image_style(str(params.get("style") or session.image_style_id)).id
    location = _resolve_start_location(params)
    state = GameState(starting_location=location)
    session.state = state

    # Send current location immediately so the map can centre.
    _send_event("location", **_state_location_payload(state))

    _send_event("loading", message="Exploring your surroundings…")
    try:
        opening = session.narrator.start_game(state)
    except (APIError, OSError, ValueError, RuntimeError) as e:
        session.last_failed_input = "I just arrived here. Look around."
        return _retryable_bail(f"Narrator error: {e}")

    if not opening.strip():
        session.last_failed_input = "I just arrived here. Look around."
        return _retryable_bail("Narrator returned an empty response")
    session.last_failed_input = None
    _publish_response(session, opening, kick_image=True)
    save_game(state)
    return {"started": True}


def _handle_load_game(session: ServerSession, params: dict[str, Any]) -> dict[str, Any]:
    name = str(params.get("name", "")).strip()
    if not name:
        return {"error": "Missing save name"}
    path = find_save_by_name(name)
    if path is None:
        return {"error": f"No save matches '{name}'"}
    try:
        state = load_game(path)
    except (OSError, ValueError, KeyError) as e:
        return {"error": f"Load failed: {e}"}

    session.state = state

    _send_event("location", **_state_location_payload(state))

    # Replay the conversation history so the UI can populate.
    history: list[dict[str, str]] = []
    for msg in state.messages:
        if msg.role == "user":
            history.append({"role": "user", "text": msg.content})
        else:
            narrative, suggestions = parse_suggestions(msg.content)
            history.append({"role": "assistant", "text": narrative})
            session.last_suggestions = suggestions
    _send_event("history", messages=history, suggestions=session.last_suggestions)

    # Populate the scene panel from the image cache; only render if this save
    # predates image caching and has no cached images yet.
    had_cached_images = _send_image_history(state)
    last_assistant = state.get_last_assistant_message()
    if last_assistant and not had_cached_images:
        _kick_image_generation(session, last_assistant)
    return {"loaded": True, "name": state.save_name or path.stem}


def _handle_input(session: ServerSession, params: dict[str, Any]) -> dict[str, Any]:
    if session.state is None:
        return {"error": "No game in progress"}

    text = str(params.get("text", "")).strip()
    if not text:
        return {"error": "Empty input"}

    _send_event("loading", message="Thinking…")
    try:
        response = session.narrator.generate_response(text, session.state)
    except (APIError, OSError, ValueError, RuntimeError) as e:
        # Roll back the user message we appended.
        session.state.pop_last_exchange()
        session.last_failed_input = text
        _send_event("error", message=f"Narrator error: {e}", can_retry=True)
        return {"error": str(e), "can_retry": True}

    if not response.strip():
        session.last_failed_input = text
        _send_event("error", message="Narrator returned an empty response", can_retry=True)
        return {"error": "Narrator returned an empty response", "can_retry": True}
    session.last_failed_input = None
    _publish_response(session, response, kick_image=True)
    save_game(session.state)
    _send_event("location", **_state_location_payload(session.state))
    return {"ok": True}


def _handle_look(session: ServerSession, _params: dict[str, Any]) -> dict[str, Any]:
    if session.state is None:
        return {"error": "No game in progress"}

    _send_event("loading", message="Looking around…")
    look_input = "Look around and describe my current surroundings in detail. Do not advance time."
    try:
        response = session.narrator.generate_response(
            look_input,
            session.state,
        )
    except (APIError, OSError, ValueError, RuntimeError) as e:
        session.state.pop_last_exchange()
        session.last_failed_input = look_input
        _send_event("error", message=f"Narrator error: {e}", can_retry=True)
        return {"error": str(e), "can_retry": True}

    if not response.strip():
        session.last_failed_input = look_input
        _send_event("error", message="Narrator returned an empty response", can_retry=True)
        return {"error": "Narrator returned an empty response", "can_retry": True}
    session.last_failed_input = None
    _publish_response(session, response, kick_image=True)
    save_game(session.state)
    return {"ok": True}


def _handle_regenerate(session: ServerSession, _params: dict[str, Any]) -> dict[str, Any]:
    if session.state is None:
        return {"error": "No game in progress"}

    last_user = session.state.pop_last_exchange()
    if last_user is None:
        return {"error": "Nothing to regenerate"}

    _send_event("loading", message="Re-rolling…")
    try:
        response = session.narrator.generate_response(last_user, session.state)
    except (APIError, OSError, ValueError, RuntimeError) as e:
        session.state.add_message("user", last_user)
        session.last_failed_input = last_user
        _send_event("error", message=f"Narrator error: {e}", can_retry=True)
        return {"error": str(e), "can_retry": True}

    if not response.strip():
        session.last_failed_input = last_user
        _send_event("error", message="Narrator returned an empty response", can_retry=True)
        return {"error": "Narrator returned an empty response", "can_retry": True}
    session.last_failed_input = None
    _publish_response(session, response, kick_image=True)
    save_game(session.state)
    return {"ok": True}


def _handle_save(session: ServerSession, params: dict[str, Any]) -> dict[str, Any]:
    if session.state is None:
        return {"error": "No game in progress"}
    name = params.get("name")
    name_str: str | None = str(name).strip() if name else None
    path = save_game(session.state, name_str or None)
    return {"path": str(path), "name": session.state.save_name}


def _handle_delete(_session: ServerSession, params: dict[str, Any]) -> dict[str, Any]:
    name = str(params.get("name", "")).strip()
    if not name:
        return {"error": "Missing save name"}
    path = find_save_by_name(name)
    if path is None:
        return {"error": f"No save matches '{name}'"}
    try:
        delete_save(path)
    except OSError as e:
        return {"error": f"Delete failed: {e}"}
    return {"deleted": True}


def _handle_render_image(session: ServerSession, params: dict[str, Any]) -> dict[str, Any]:
    if session.state is None:
        return {"error": "No game in progress"}
    last_assistant = session.state.get_last_assistant_message()
    if last_assistant is None:
        return {"error": "No scene to render"}
    style = get_image_style(_clean_param_str(params.get("style")))
    session.image_style_id = style.id
    _kick_image_generation(session, last_assistant, style.id)
    return {"ok": True, "style": style.id}


def _handle_cost(session: ServerSession, _params: dict[str, Any]) -> dict[str, Any]:
    return {
        "usd": session.narrator.get_session_cost(),
        "opus_input": session.narrator.opus_input_tokens,
        "opus_output": session.narrator.opus_output_tokens,
        "sonnet_input": session.narrator.sonnet_input_tokens,
        "sonnet_output": session.narrator.sonnet_output_tokens,
    }


# --- Helpers --------------------------------------------------------------


def _latest_cached_image_for_save(save_path: Any) -> dict[str, str] | None:
    try:
        with open(save_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    image_history = data.get("image_history")
    if not isinstance(image_history, list):
        return None

    for item in reversed(image_history):
        if not isinstance(item, dict):
            continue
        rel_path = _clean_param_str(item.get("path"))
        if rel_path is None:
            continue
        abs_path = DATA_DIR / rel_path
        if abs_path.exists():
            return {
                "path": str(abs_path),
                "style_name": str(item.get("style_name") or "Scene render"),
            }
    return None


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_param_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "<null>":
        return None
    return text


def _resolve_start_location(params: dict[str, Any]) -> Location:
    """Resolve the GUI's free-form start field into a real location.

    The UI starts with IP-detected city data, but the user can replace the
    field with something like "Miami". In that case the old detected city and
    coordinates must not leak into the new game.
    """
    address = _clean_param_str(params.get("address"))
    if address:
        geocoded = geocode_location(address)
        if geocoded is not None:
            return geocoded
        return Location(city=address, region="", country="", address=address)

    return Location(
        city=str(params.get("city", "")),
        region=str(params.get("region", "")),
        country=str(params.get("country", "")),
        latitude=_optional_float(params.get("latitude")),
        longitude=_optional_float(params.get("longitude")),
    )


def _bail(message: str) -> dict[str, Any]:
    _send_event("error", message=message)
    return {"error": message}


def _retryable_bail(message: str) -> dict[str, Any]:
    _send_event("error", message=message, can_retry=True)
    return {"error": message, "can_retry": True}


def _handle_retry_fallback(session: ServerSession, params: dict[str, Any]) -> dict[str, Any]:
    if session.state is None:
        return {"error": "No game in progress"}
    if not session.last_failed_input:
        return {"error": "No failed narrator turn to retry"}
    model = _clean_param_str(params.get("model")) or os.getenv("RWTA_FALLBACK_MODEL", "gpt-5.5")
    retry_input = session.last_failed_input
    _send_event("loading", message=f"Retrying with {model}…")
    try:
        response = session.narrator.generate_response_fallback(
            retry_input, session.state, model=model
        )
    except (RuntimeError, OSError, ValueError) as e:
        _send_event("error", message=str(e), can_retry=True)
        return {"error": str(e), "can_retry": True}

    session.last_failed_input = None
    _publish_response(session, response, kick_image=True)
    save_game(session.state)
    _send_event("location", **_state_location_payload(session.state))
    return {"ok": True, "model": model}


def _publish_response(session: ServerSession, raw: str, *, kick_image: bool) -> None:
    """Parse a narrator response and broadcast its narrative + suggestions."""
    narrative, suggestions = parse_suggestions(raw)
    session.last_suggestions = suggestions
    _send_event("narrative", text=narrative)
    _send_event("suggestions", items=suggestions)
    if session.state is not None:
        _send_event("location", **_state_location_payload(session.state))
    if kick_image:
        _kick_image_generation(session, raw)


def _latest_assistant_index(state: GameState) -> int | None:
    for idx in range(len(state.messages) - 1, -1, -1):
        if state.messages[idx].role == "assistant":
            return idx
    return None


def _image_cache_dir(state: GameState) -> str:
    if state.save_name is None:
        save_game(state)
    safe_name = "".join(c for c in str(state.save_name) if c.isalnum() or c in "._-")
    return str(DATA_DIR / "images" / safe_name)


def _absolute_image_path(entry: ImageHistoryEntry) -> str:
    path = DATA_DIR / entry.path
    return str(path)


def _image_entry_payload(entry: ImageHistoryEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "turn_index": entry.turn_index,
        "style_id": entry.style_id,
        "style_name": entry.style_name,
        "path": _absolute_image_path(entry),
        "prompt": entry.prompt,
        "created_at": entry.created_at,
    }


def _send_image_history(state: GameState, selected_id: str | None = None) -> bool:
    entries = [
        entry for entry in state.image_history if os.path.exists(_absolute_image_path(entry))
    ]
    if len(entries) != len(state.image_history):
        state.image_history = entries
        save_game(state)
    selected_index = len(entries) - 1
    if selected_id is not None:
        for idx, entry in enumerate(entries):
            if entry.id == selected_id:
                selected_index = idx
                break
    _send_event(
        "image_history",
        entries=[_image_entry_payload(entry) for entry in entries],
        selected_index=selected_index,
    )
    if entries and selected_index >= 0:
        _send_event("image", **_image_entry_payload(entries[selected_index]))
        return True
    return False


def _cached_image_for_turn(
    state: GameState, turn_index: int, style_id: str
) -> ImageHistoryEntry | None:
    for entry in reversed(state.image_history):
        if (
            entry.turn_index == turn_index
            and entry.style_id == style_id
            and os.path.exists(_absolute_image_path(entry))
        ):
            return entry
    return None


def _cache_scene_image(
    state: GameState,
    *,
    b64_png: str,
    turn_index: int,
    style_id: str,
    style_name: str,
    prompt: str,
) -> ImageHistoryEntry:
    cache_dir = _image_cache_dir(state)
    os.makedirs(cache_dir, exist_ok=True)
    filename = f"turn-{turn_index:04d}-{style_id}.png"
    abs_path = os.path.join(cache_dir, filename)
    with open(abs_path, "wb") as f:
        f.write(base64.b64decode(b64_png))
    rel_path = os.path.relpath(abs_path, DATA_DIR)
    entry = ImageHistoryEntry(
        id=f"turn-{turn_index:04d}-{style_id}",
        turn_index=turn_index,
        style_id=style_id,
        style_name=style_name,
        path=rel_path,
        prompt=prompt,
    )
    state.image_history = [img for img in state.image_history if img.id != entry.id]
    state.image_history.append(entry)
    save_game(state)
    return entry


def _kick_image_generation(
    session: ServerSession, raw_narrative: str, style_id: str | None = None
) -> None:
    """Spawn a background thread to generate a scene image, using cache if available."""
    state = session.state
    if state is None:
        return

    style = get_image_style(style_id or session.image_style_id)
    session.image_style_id = style.id
    turn_index = _latest_assistant_index(state)
    if turn_index is None:
        return

    cached = _cached_image_for_turn(state, turn_index, style.id)
    if cached is not None:
        _send_event("image_loading", loading=False, style_id=style.id)
        _send_image_history(state, selected_id=cached.id)
        return

    # If a previous image gen is still running, let it finish; otherwise we'd
    # cancel it without OpenAI knowing and waste a request. The newer one
    # will overwrite the older one in the UI when it lands.
    loc = state.get_current_location()
    location_str = str(loc)
    game_time = state.get_formatted_game_time()
    weather = get_cached_weather(loc)
    weather_str = str(weather) if weather else None
    narrative, _ = parse_suggestions(raw_narrative)
    visual_continuity = state.visual_continuity

    def run() -> None:
        _send_event("image_loading", loading=True, style_id=style.id)
        scene = generate_scene_image(
            narrative=narrative,
            location_str=location_str,
            game_time_str=game_time,
            weather_str=weather_str,
            visual_continuity=visual_continuity,
            style_id=style.id,
        )

        _send_event("image_loading", loading=False, style_id=style.id)
        if scene is None:
            _send_event("image_error", message="Image generation skipped or failed")
            return
        try:
            entry = _cache_scene_image(
                state,
                b64_png=scene.b64_png,
                turn_index=turn_index,
                style_id=scene.style.id,
                style_name=scene.style.name,
                prompt=scene.prompt,
            )
        except (OSError, ValueError, TypeError) as e:
            logger.warning("Image cache write failed: %s", e)
            _send_event("image_error", message=f"Image cache write failed: {e}")
            return
        _send_image_history(state, selected_id=entry.id)
        _send_event("image", data=scene.b64_png, **_image_entry_payload(entry))

    thread = threading.Thread(target=run, daemon=True, name="rwta-imagegen")
    thread.start()
    session.image_thread = thread


METHODS: dict[str, Callable[[ServerSession, dict[str, Any]], dict[str, Any]]] = {
    "list_saves": _handle_list_saves,
    "detect_location": _handle_detect_location,
    "new_game": _handle_new_game,
    "load_game": _handle_load_game,
    "input": _handle_input,
    "look": _handle_look,
    "regenerate": _handle_regenerate,
    "save": _handle_save,
    "delete": _handle_delete,
    "render_image": _handle_render_image,
    "retry_fallback": _handle_retry_fallback,
    "cost": _handle_cost,
}


def _dispatch(session: ServerSession, request: dict[str, Any]) -> None:
    req_id = request.get("id")
    method = str(request.get("method", ""))
    params = request.get("params") or {}
    if not isinstance(params, dict):
        params = {}

    handler = METHODS.get(method)
    if handler is None:
        _send_error(req_id, f"Unknown method: {method}")
        return

    try:
        result = handler(session, params)
    except KeyboardInterrupt:
        raise
    except (APIError, OSError, ValueError, KeyError, TypeError, RuntimeError) as e:
        logger.exception("Handler %s failed", method)
        _send_error(req_id, f"{type(e).__name__}: {e}")
        return

    if isinstance(result, dict) and "error" in result and len(result) == 1:
        _send_error(req_id, str(result["error"]))
    else:
        _send_result(req_id, result)


def serve(fast: bool = False) -> int:
    """Run the JSON-RPC loop until stdin closes."""
    log_level = os.getenv("RWTA_LOG_LEVEL", "WARNING").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.WARNING),
        format="%(name)s %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    if not os.environ.get("ANTHROPIC_API_KEY"):
        _send_event("fatal", message="ANTHROPIC_API_KEY is not set")
        return 1

    narrator = GameNarrator(fast=fast)
    session = ServerSession(narrator=narrator, fast=fast)

    _send_event(
        "ready",
        data_dir=str(DATA_DIR),
        timezone=str(LOCAL_TIMEZONE),
        fast=fast,
        has_openai_key=bool(os.environ.get("OPENAI_API_KEY")),
        image_styles=list_image_styles(),
        default_image_style="photo",
    )

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            _send_event("error", message=f"Bad JSON: {e}")
            continue
        if not isinstance(request, dict):
            _send_event("error", message="Request must be a JSON object")
            continue
        if request.get("method") == "quit":
            _send_result(request.get("id"), {"bye": True})
            break
        _dispatch(session, request)

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rwta-gui-server")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use the fast model (Sonnet) for narration.",
    )
    args = parser.parse_args(argv)
    return serve(fast=args.fast)


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["main", "serve"]
