"""
Latency tracking for Voice Live Avatar sessions.

Captures per-turn timestamps for the key points in a voice-to-voice exchange and
emits both human-readable console logs and structured JSONL records.

Per-turn timeline (one "turn" = one user utterance → one assistant response):

    speech_started ─► speech_stopped ─► user_transcript_done
                                  └──► response_created ─► first_audio_delta ─► audio_done ─► response_done

The headline metric is **EOU → first audio** (time from when the server VAD said
the user stopped talking to when the first byte of synthesised audio arrived).
This is what listeners perceive as the assistant's "reaction time".

Browser-side timestamps (first audio actually played, first avatar video frame)
are merged in via :meth:`LatencyTracker.merge_client_metrics` so a single record
captures the full mouth-to-ear path.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ANSI colours for the [LATENCY] console line (kept compatible with ColorFormatter).
_C_RESET = "\033[0m"
_C_BOLD = "\033[1m"
_C_DIM = "\033[2m"
_C_MAGENTA = "\033[35m"
_C_CYAN = "\033[36m"
_C_YELLOW = "\033[33m"
_C_GREEN = "\033[32m"
_C_RED = "\033[31m"


def _now_ms() -> float:
    """Monotonic millisecond clock for computing deltas."""
    return time.perf_counter() * 1000.0


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class TurnRecord:
    """Timestamps and derived metrics for one assistant response."""

    turn: int
    started_at: str = field(default_factory=_iso_now)

    # Raw perf_counter timestamps (ms). None until the event fires.
    t_speech_started: Optional[float] = None
    t_speech_stopped: Optional[float] = None
    t_user_transcript_done: Optional[float] = None
    t_response_created: Optional[float] = None
    t_first_audio_delta: Optional[float] = None
    t_audio_done: Optional[float] = None
    t_response_done: Optional[float] = None

    # Browser-reported timestamps (ms since the same epoch as the others is
    # impossible across processes — we instead store delta_from_server_event ms).
    client_first_audio_offset_ms: Optional[float] = None
    client_first_response_offset_ms: Optional[float] = None

    # Context
    response_id: str = ""
    user_item_id: str = ""
    user_transcript: str = ""
    assistant_transcript: str = ""

    def metrics(self) -> dict[str, Optional[float]]:
        """Compute derived deltas (all in milliseconds, rounded to 1 ms)."""
        def d(a: Optional[float], b: Optional[float]) -> Optional[float]:
            if a is None or b is None:
                return None
            return round(b - a, 1)

        return {
            # User-side
            "user_speech_duration_ms": d(self.t_speech_started, self.t_speech_stopped),
            "stt_latency_ms": d(self.t_speech_stopped, self.t_user_transcript_done),
            # Headline: EOU → first audio (the "reaction time")
            "eou_to_first_audio_ms": d(self.t_speech_stopped, self.t_first_audio_delta),
            # Breakdown of that headline
            "eou_to_response_created_ms": d(self.t_speech_stopped, self.t_response_created),
            "response_created_to_first_audio_ms": d(
                self.t_response_created, self.t_first_audio_delta
            ),
            # Audio stream duration (synth + transport)
            "first_audio_to_audio_done_ms": d(self.t_first_audio_delta, self.t_audio_done),
            "first_audio_to_response_done_ms": d(
                self.t_first_audio_delta, self.t_response_done
            ),
            # End-to-end perceived latency (server EOU → first byte heard in browser)
            "eou_to_client_first_audio_ms": (
                round(
                    (self.t_first_audio_delta - self.t_speech_stopped)
                    + (self.client_first_audio_offset_ms or 0),
                    1,
                )
                if self.t_first_audio_delta is not None
                and self.t_speech_stopped is not None
                and self.client_first_audio_offset_ms is not None
                else None
            ),
            # End-to-end perceived latency via the response-chunk path (works in
            # webrtc avatar mode where audio doesn't pass through the relay).
            "eou_to_client_first_response_ms": (
                round(
                    (self.t_first_audio_delta - self.t_speech_stopped)
                    + (self.client_first_response_offset_ms or 0),
                    1,
                )
                if self.t_first_audio_delta is not None
                and self.t_speech_stopped is not None
                and self.client_first_response_offset_ms is not None
                else None
            ),
        }


@dataclass
class SessionInfo:
    """Static session metadata included with each JSONL record."""

    client_id: str
    model: str = ""
    mode: str = ""
    voice: str = ""
    avatar_enabled: bool = False
    avatar_output_mode: str = ""
    turn_detection: str = ""

    # Session-level timings (set once)
    t_session_start: Optional[float] = None
    t_session_ready: Optional[float] = None
    t_avatar_sdp_offer: Optional[float] = None
    t_avatar_connected: Optional[float] = None


class LatencyTracker:
    """Per-session latency tracker. One instance per `VoiceSessionHandler`."""

    def __init__(
        self,
        client_id: str,
        send_message: Optional[Callable] = None,
        jsonl_path: Optional[str] = None,
        enabled: bool = True,
    ):
        self.enabled = enabled
        self.send_message = send_message
        self.jsonl_path = jsonl_path
        self.session = SessionInfo(client_id=client_id)
        self._turns: list[TurnRecord] = []
        self._current: Optional[TurnRecord] = None
        self._turn_counter = 0

    # ---------- session-level ----------

    def set_session_metadata(
        self,
        *,
        model: str = "",
        mode: str = "",
        voice: str = "",
        avatar_enabled: bool = False,
        avatar_output_mode: str = "",
        turn_detection: str = "",
    ) -> None:
        s = self.session
        s.model = model
        s.mode = mode
        s.voice = voice
        s.avatar_enabled = avatar_enabled
        s.avatar_output_mode = avatar_output_mode
        s.turn_detection = turn_detection

    def mark_session_start(self) -> None:
        self.session.t_session_start = _now_ms()

    def mark_session_ready(self) -> None:
        if not self.enabled:
            return
        self.session.t_session_ready = _now_ms()
        if self.session.t_session_start is not None:
            dt = self.session.t_session_ready - self.session.t_session_start
            logger.info(
                f"{_C_MAGENTA}{_C_BOLD}[LATENCY]{_C_RESET} session_ready in "
                f"{_C_BOLD}{dt:.0f} ms{_C_RESET} "
                f"{_C_DIM}(model={self.session.model} mode={self.session.mode}){_C_RESET}"
            )

    def mark_avatar_sdp_offer(self) -> None:
        self.session.t_avatar_sdp_offer = _now_ms()

    def mark_avatar_connected(self) -> None:
        if not self.enabled:
            return
        self.session.t_avatar_connected = _now_ms()
        if self.session.t_avatar_sdp_offer is not None:
            dt = self.session.t_avatar_connected - self.session.t_avatar_sdp_offer
            logger.info(
                f"{_C_MAGENTA}{_C_BOLD}[LATENCY]{_C_RESET} avatar_sdp_roundtrip "
                f"{_C_BOLD}{dt:.0f} ms{_C_RESET}"
            )

    # ---------- per-turn ----------

    def _ensure_current(self) -> TurnRecord:
        if self._current is None:
            self._turn_counter += 1
            self._current = TurnRecord(turn=self._turn_counter)
        return self._current

    def mark_speech_started(self, item_id: str = "") -> None:
        if not self.enabled:
            return
        # A new user utterance starts a new turn. If a prior turn never completed
        # (e.g. user barged-in), flush whatever we have so the row isn't lost.
        if self._current is not None:
            self._flush_current(reason="superseded")

        self._turn_counter += 1
        self._current = TurnRecord(turn=self._turn_counter)
        self._current.t_speech_started = _now_ms()
        self._current.user_item_id = item_id

    def mark_speech_stopped(self) -> None:
        if not self.enabled or self._current is None:
            return
        self._current.t_speech_stopped = _now_ms()

    def mark_user_transcript_done(self, item_id: str, transcript: str) -> None:
        if not self.enabled:
            return
        cur = self._ensure_current()
        cur.t_user_transcript_done = _now_ms()
        cur.user_transcript = transcript

    def mark_response_created(self, response_id: str) -> None:
        if not self.enabled:
            return
        cur = self._ensure_current()
        cur.t_response_created = _now_ms()
        cur.response_id = response_id

    def mark_first_audio_delta(self) -> None:
        if not self.enabled or self._current is None:
            return
        if self._current.t_first_audio_delta is None:
            self._current.t_first_audio_delta = _now_ms()

    def mark_audio_done(self) -> None:
        if not self.enabled or self._current is None:
            return
        self._current.t_audio_done = _now_ms()

    def set_assistant_transcript(self, transcript: str) -> None:
        if not self.enabled or self._current is None:
            return
        self._current.assistant_transcript = transcript

    def mark_response_done(self) -> None:
        if not self.enabled or self._current is None:
            return
        self._current.t_response_done = _now_ms()
        self._flush_current(reason="done")

    def merge_client_metrics(self, payload: dict) -> None:
        """Receive a `latency_client` message from the browser.

        Payload schema:
            {"turn": <int|null>,
             "response_id": <str|null>,
             "first_audio_offset_ms": <float|null>,
             "first_video_offset_ms": <float|null>}

        The browser reports the offset (ms) between *its own* receipt of the
        `response_created` event and the moment it actually played/rendered the
        first sample/frame. We then add server-side ``eou → first_audio`` to
        derive the perceived end-to-end latency.
        """
        if not self.enabled:
            return

        target: Optional[TurnRecord] = None
        rid = (payload.get("response_id") or "").strip()
        if rid:
            for t in reversed(self._turns):
                if t.response_id == rid:
                    target = t
                    break
        if target is None and self._current is not None:
            target = self._current
        elif target is None and self._turns:
            target = self._turns[-1]
        if target is None:
            return

        fa = payload.get("first_audio_offset_ms")
        fr = payload.get("first_response_offset_ms")
        if isinstance(fa, (int, float)):
            target.client_first_audio_offset_ms = float(fa)
        if isinstance(fr, (int, float)):
            target.client_first_response_offset_ms = float(fr)

        # Re-emit the line so the dev console reflects the perceived numbers.
        self._log_turn(target, suffix=" (client-updated)")

    # ---------- emit ----------

    def _flush_current(self, *, reason: str) -> None:
        if self._current is None:
            return
        rec = self._current
        self._current = None
        self._turns.append(rec)
        self._log_turn(rec)
        self._write_jsonl(rec)
        self._notify_client(rec)

    def _log_turn(self, rec: TurnRecord, *, suffix: str = "") -> None:
        m = rec.metrics()

        def _fmt(name: str, val: Optional[float], colour: str = _C_CYAN) -> str:
            if val is None:
                return f"{_C_DIM}{name}=–{_C_RESET}"
            return f"{name}={colour}{_C_BOLD}{val:.0f}ms{_C_RESET}"

        headline = m.get("eou_to_first_audio_ms")
        headline_colour = (
            _C_GREEN if (headline is not None and headline < 800)
            else _C_YELLOW if (headline is not None and headline < 1500)
            else _C_RED
        )

        parts = [
            f"{_C_MAGENTA}{_C_BOLD}[LATENCY]{_C_RESET}",
            f"turn={_C_BOLD}{rec.turn}{_C_RESET}",
            _fmt("EOU→first_audio", headline, headline_colour),
            _fmt("create", m.get("eou_to_response_created_ms")),
            _fmt("TTFB", m.get("response_created_to_first_audio_ms")),
            _fmt("audio_dur", m.get("first_audio_to_audio_done_ms")),
            _fmt("stt", m.get("stt_latency_ms")),
        ]
        if m.get("eou_to_client_first_audio_ms") is not None:
            parts.append(_fmt("→ear", m["eou_to_client_first_audio_ms"], _C_MAGENTA))
        if m.get("eou_to_client_first_response_ms") is not None:
            parts.append(_fmt("→resp", m["eou_to_client_first_response_ms"], _C_MAGENTA))
        logger.info(" ".join(parts) + suffix)

    def _write_jsonl(self, rec: TurnRecord) -> None:
        if not self.jsonl_path:
            return
        try:
            os.makedirs(os.path.dirname(self.jsonl_path) or ".", exist_ok=True)
            payload = {
                "ts": _iso_now(),
                "client_id": self.session.client_id,
                "turn": rec.turn,
                "response_id": rec.response_id,
                "user_item_id": rec.user_item_id,
                "user_transcript": rec.user_transcript,
                "assistant_transcript": rec.assistant_transcript,
                "session": {
                    "model": self.session.model,
                    "mode": self.session.mode,
                    "voice": self.session.voice,
                    "avatar_enabled": self.session.avatar_enabled,
                    "avatar_output_mode": self.session.avatar_output_mode,
                    "turn_detection": self.session.turn_detection,
                },
                "metrics": rec.metrics(),
            }
            with open(self.jsonl_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, separators=(",", ":")) + "\n")
        except Exception as e:  # noqa: BLE001 — never let logging kill a session
            logger.warning(f"[LATENCY] failed to write jsonl: {e}")

    def _notify_client(self, rec: TurnRecord) -> None:
        if not self.send_message:
            return
        try:
            payload = {
                "type": "latency_metrics",
                "turn": rec.turn,
                "responseId": rec.response_id,
                "userTranscript": rec.user_transcript,
                "metrics": rec.metrics(),
            }
            # Fire-and-forget; send_message is an async callable.
            import asyncio

            coro = self.send_message(payload)
            if asyncio.iscoroutine(coro):
                asyncio.create_task(coro)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[LATENCY] failed to notify client: {e}")

    # ---------- helpers ----------

    @property
    def turns(self) -> list[TurnRecord]:
        return list(self._turns)
