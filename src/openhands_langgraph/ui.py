from __future__ import annotations

import json
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from openhands.client import extract_message_text, format_event

try:  # Rich is an optional runtime dependency for the pretty graph UI.
    from rich import box
    from rich.console import Console, Group
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.syntax import Syntax
    from rich.table import Table
    from rich.text import Text
except Exception:  # pragma: no cover - exercised when rich is intentionally absent.
    box = None  # type: ignore[assignment]
    Console = None  # type: ignore[assignment]
    Group = None  # type: ignore[assignment]
    Live = None  # type: ignore[assignment]
    Markdown = None  # type: ignore[assignment]
    Panel = None  # type: ignore[assignment]
    Syntax = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]
    Text = None  # type: ignore[assignment]

JsonDict = dict[str, Any]

ROLE_STYLES = {
    "team_lead": "bright_cyan",
    "scout": "cyan",
    "research": "blue",
    "senior_staff_engineer": "magenta",
    "architect": "purple",
    "coder": "green",
    "qa": "bright_green",
    "reviewer": "yellow",
    "publisher": "bright_blue",
    "role": "white",
}

EVENT_STYLES = {
    "socket": "bright_black",
    "status": "bright_blue",
    "state": "dim",
    "user": "cyan",
    "assistant": "green",
    "action": "yellow",
    "observation": "magenta",
    "error": "bold red",
    "event": "white",
}


@dataclass
class EventLine:
    text: str
    style: str = "white"
    kind: str = "event"

    def __str__(self) -> str:  # Keeps tests/old callers that cast events to str working.
        return self.text


@dataclass
class RoleUIState:
    role: str
    prompt: str = ""
    prompt_digest: list[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)
    status: str = "running"
    conversation_id: str | None = None
    last_events: deque[Any] = field(default_factory=lambda: deque(maxlen=5))
    answer: str = ""
    summary: str = ""
    action: str = ""
    risk: str = ""
    blocking: Any = None
    prompt_chars: int = 0
    answer_chars: int = 0
    event_count: int = 0


class NullWorkflowUI:
    """No-op UI with the same public methods as RichWorkflowUI."""

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def role_start(self, role: str, prompt: str, *, title: str | None = None, state: JsonDict | None = None) -> None:
        pass

    def role_event_callback(self, role: str):
        def _callback(event: JsonDict) -> None:
            return None

        return _callback

    def role_result(self, role: str, result: JsonDict) -> None:
        pass

    def team_lead_decision_prompt(self, prompt: str, *, state: JsonDict | None = None) -> None:
        pass

    def team_lead_decision_result(self, result: JsonDict) -> None:
        pass

    def final_result(self, result: JsonDict) -> None:
        pass


class RichWorkflowUI(NullWorkflowUI):
    """Real-time Rich dashboard for OpenHands LangGraph runs.

    The dashboard is intentionally an operator view, not a state authority. It
    renders only compact prompt substitutions/context, the last five websocket
    events in real time, and answer/summary previews. Full prompts are no longer
    printed because they drown out the live operational signal.
    """

    def __init__(
        self,
        *,
        console: Any | None = None,
        prompt_max_chars: int = 6000,
        answer_max_chars: int = 8000,
        refresh_per_second: float = 8.0,
        transient: bool = False,
    ) -> None:
        if Console is None or Live is None:
            raise RuntimeError("Rich UI requested but the 'rich' package is not installed")
        self.console = console or Console(stderr=False)
        # Kept for CLI compatibility; now caps the compact prompt digest instead
        # of showing the full prompt body.
        self.prompt_max_chars = max(500, int(prompt_max_chars))
        self.answer_max_chars = max(500, int(answer_max_chars))
        self.refresh_per_second = refresh_per_second
        self.transient = transient
        self.current: RoleUIState | None = None
        self.completed: list[RoleUIState] = []
        self.live: Any | None = None
        self.started_at = time.monotonic()
        self.workflow_status = "running"

    def start(self) -> None:
        if self.live is None:
            self.live = Live(
                self.render(),
                console=self.console,
                refresh_per_second=self.refresh_per_second,
                transient=self.transient,
                auto_refresh=False,
            )
            self.live.start(refresh=True)

    def stop(self) -> None:
        if self.live is not None:
            self.live.update(self.render(), refresh=True)
            self.live.stop()
            self.live = None

    def _refresh(self) -> None:
        if self.live is not None:
            self.live.update(self.render(), refresh=True)

    def role_start(self, role: str, prompt: str, *, title: str | None = None, state: JsonDict | None = None) -> None:
        digest = build_prompt_digest(role, prompt, state=state, max_chars=self.prompt_max_chars)
        self.current = RoleUIState(
            role=role,
            prompt=prompt or "",
            prompt_digest=digest,
            prompt_chars=len(prompt or ""),
        )
        self.current.last_events.append(EventLine(f"role started: {title or role}", EVENT_STYLES["status"], "status"))
        self._refresh()

    def role_event_callback(self, role: str):
        def _callback(event: JsonDict) -> None:
            if self.current is None or self.current.role != role:
                return
            line = format_event(event, raw=False, debug=False)
            if not line:
                return
            self.current.event_count += 1
            self.current.last_events.append(classify_event_line(event, line))
            text = extract_message_text(event)
            if text and str(event.get("kind") or "") == "MessageEvent" and str(event.get("source") or "") == "agent":
                self.current.answer = text
                self.current.answer_chars = len(text)
            self._refresh()

        return _callback

    def role_result(self, role: str, result: JsonDict) -> None:
        if self.current is None or self.current.role != role:
            self.current = RoleUIState(role=role)
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        self.current.status = str(result.get("summary_status") or summary.get("status") or result.get("status") or "completed")
        self.current.action = str(result.get("summary_action") or summary.get("action") or "")
        self.current.risk = str(result.get("risk_level") or summary.get("risk_level") or "")
        self.current.blocking = result.get("blocking") if result.get("blocking") is not None else summary.get("blocking")
        self.current.summary = str(summary.get("summary") or "")
        self.current.answer = str(result.get("answer") or self.current.answer or "")
        self.current.answer_chars = len(self.current.answer)
        self.current.conversation_id = str(result.get("conversation_id") or "") or None
        self.current.last_events.append(
            EventLine(
                f"role completed: action={self.current.action or 'unknown'} status={self.current.status}",
                EVENT_STYLES["status"],
                "status",
            )
        )
        self.completed.append(self.current)
        self.current = None
        self._refresh()

    def team_lead_decision_prompt(self, prompt: str, *, state: JsonDict | None = None) -> None:
        self.role_start("team_lead", prompt, title="direct LLM decision", state=state)

    def team_lead_decision_result(self, result: JsonDict) -> None:
        self.role_result("team_lead", result)

    def final_result(self, result: JsonDict) -> None:
        self.workflow_status = str(result.get("final_status") or "finished")
        self._refresh()

    def render(self) -> Any:
        sections: list[Any] = [self._render_header(), self._render_role_table()]
        if self.current is not None:
            sections.append(self._render_current_role(self.current))
        elif self.completed:
            sections.append(self._render_last_completed(self.completed[-1]))
        return Group(*sections)

    def _render_header(self) -> Any:
        elapsed = time.monotonic() - self.started_at
        text = Text()
        text.append("OpenHands Team Pipeline", style="bold bright_white")
        text.append(f"  status={self.workflow_status}", style="dim")
        text.append(f"  elapsed={_duration(elapsed)}", style="dim")
        text.append("  live=ws:last5", style="bright_black")
        return Panel(text, border_style="bright_blue", box=box.ROUNDED)

    def _render_role_table(self) -> Any:
        table = Table(title="Roles", box=box.SIMPLE_HEAVY, expand=True)
        table.add_column("#", justify="right", style="dim", width=3)
        table.add_column("Role")
        table.add_column("Action", width=12)
        table.add_column("Risk", width=10)
        table.add_column("Duration", width=10)
        table.add_column("Conversation / Summary", ratio=2)
        for idx, item in enumerate(self.completed[-10:], start=max(1, len(self.completed) - 9)):
            style = ROLE_STYLES.get(item.role, "white")
            table.add_row(
                str(idx),
                Text(item.role, style=style),
                item.action or "-",
                item.risk or "-",
                _duration(time.monotonic() - item.started_at),
                _clip(item.summary or item.conversation_id or "", 160),
            )
        if self.current is not None:
            style = ROLE_STYLES.get(self.current.role, "white")
            table.add_row(
                str(len(self.completed) + 1),
                Text(self.current.role + " ⏳", style=style),
                "running",
                "-",
                _duration(time.monotonic() - self.current.started_at),
                f"ws_events={self.current.event_count} prompt={self.current.prompt_chars} chars",
            )
        return table

    def _render_current_role(self, item: RoleUIState) -> Any:
        style = ROLE_STYLES.get(item.role, "white")
        answer = _clip_multiline(item.answer, self.answer_max_chars) if item.answer else "Waiting for assistant answer..."
        return Group(
            Panel(Text(f"{item.role} running", style=f"bold {style}"), border_style=style, box=box.ROUNDED),
            Panel(_render_prompt_digest(item.prompt_digest), title="Prompt context / substitutions", border_style="cyan", box=box.ROUNDED),
            Panel(_render_events(item.last_events), title="Live websocket events — last 5", border_style="yellow", box=box.ROUNDED),
            Panel(_render_text_block(answer, language="markdown"), title=f"Answer preview ({item.answer_chars} chars)", border_style="green", box=box.ROUNDED),
        )

    def _render_last_completed(self, item: RoleUIState) -> Any:
        style = ROLE_STYLES.get(item.role, "white")
        answer = _clip_multiline(item.answer, self.answer_max_chars) if item.answer else "[no answer captured]"
        summary = item.summary or "[no summary]"
        return Group(
            Panel(Text(f"Last completed: {item.role} action={item.action or '-'} risk={item.risk or '-'}", style=f"bold {style}"), border_style=style, box=box.ROUNDED),
            Panel(_render_text_block(summary, language="markdown"), title="Summary", border_style="blue", box=box.ROUNDED),
            Panel(_render_events(item.last_events), title="Last websocket events", border_style="yellow", box=box.ROUNDED),
            Panel(_render_text_block(answer, language="markdown"), title=f"Role answer ({item.answer_chars} chars)", border_style="green", box=box.ROUNDED),
        )


def make_workflow_ui(kind: str, *, no_color: bool = False) -> NullWorkflowUI:
    kind = (kind or "plain").lower()
    if kind in {"off", "none", "plain", "classic"}:
        return NullWorkflowUI()
    if kind == "rich":
        if Console is None:
            raise RuntimeError("--ui rich requires 'rich'. Install with pip install rich or use --ui plain")
        return RichWorkflowUI(console=Console(no_color=no_color))
    if kind == "auto":
        if Console is None:
            return NullWorkflowUI()
        return RichWorkflowUI(console=Console(no_color=no_color))
    raise ValueError(f"Unknown UI mode: {kind}")


def build_prompt_digest(role: str, prompt: str, *, state: JsonDict | None = None, max_chars: int = 6000) -> list[str]:
    """Return compact prompt substitutions/context instead of the full prompt.

    The full role prompt contains long static policy text. Operators usually need
    the values substituted into it: task, repository, validation profile, upstream
    reports, Team Lead assignment, and current workflow position. Prefer state
    based summaries; fall back to extracting high-value headings from the prompt.
    """
    lines: list[str] = []
    role_key = (role or "role").lower()
    if state:
        lines.append(f"role: {role_key}")
        task = state.get("user_task") or state.get("prompt") or ""
        if task:
            lines.append(f"task: {_clip(str(task), 260)}")
        if state.get("repository"):
            lines.append(f"repository: {state.get('repository')}")
        if state.get("branch"):
            lines.append(f"branch: {state.get('branch')}")
        if state.get("workflow"):
            lines.append(f"workflow: {state.get('workflow')}")
        if state.get("team_lead_steps") is not None or state.get("max_team_lead_steps") is not None:
            lines.append(f"team_lead_step: {state.get('team_lead_steps', 0)}/{state.get('max_team_lead_steps', '?')}")
        decision = state.get("team_lead_decision")
        if isinstance(decision, dict) and decision:
            lines.append("team_lead_assignment:")
            for key in ("action", "next_role", "role_instance", "instructions"):
                if decision.get(key):
                    lines.append(f"  - {key}: {_clip(decision.get(key), 280)}")
            policy = decision.get("policy_evaluation")
            if isinstance(policy, dict) and policy:
                useful = {k: policy.get(k) for k in sorted(policy) if policy.get(k) not in (None, "", [], {})}
                if useful:
                    lines.append(f"  - policy: {_clip(json.dumps(useful, ensure_ascii=False, sort_keys=True), 360)}")
        try:
            from .prompts import role_input_summary
            for item in role_input_summary(role_key, state):
                if item and item not in lines:
                    lines.append(_clip(item, 360))
        except Exception:
            pass
        profile = state.get("validation_profile")
        if isinstance(profile, dict) and profile:
            compact_profile = _compact_dict(profile, max_chars=800)
            lines.append(f"validation_profile: {compact_profile}")
        role_results = state.get("role_results") if isinstance(state.get("role_results"), list) else []
        if role_results:
            lines.append("latest_reports:")
            for result in role_results[-5:]:
                if not isinstance(result, dict):
                    continue
                summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
                lines.append(
                    "  - "
                    + f"{result.get('role')}: action={result.get('summary_action') or summary.get('action') or '?'} "
                    + f"risk={result.get('risk_level') or summary.get('risk_level') or '?'} "
                    + _clip(summary.get("summary") or "", 220)
                )
    else:
        lines.append(f"role: {role_key}")
        lines.extend(_extract_prompt_dynamic_snippets(prompt))

    if not lines:
        lines.extend(_extract_prompt_dynamic_snippets(prompt))
    if not lines:
        lines.append(f"full prompt hidden ({len(prompt or '')} chars); no compact substitutions detected")
    return _cap_lines(lines, max_chars=max_chars)


def classify_event_line(event: JsonDict, line: str) -> EventLine:
    kind = str(event.get("kind") or "")
    if "_websocket" in event or line.startswith("[socket]"):
        return EventLine(line, EVENT_STYLES["socket"], "socket")
    if "error" in line.lower() or "failed" in line.lower() or "exception" in line.lower():
        return EventLine(line, EVENT_STYLES["error"], "error")
    if kind == "MessageEvent":
        source = str(event.get("source") or "")
        if source == "user" or line.startswith("[user]"):
            return EventLine(line, EVENT_STYLES["user"], "user")
        return EventLine(line, EVENT_STYLES["assistant"], "assistant")
    if kind == "ActionEvent" or line.startswith("[action") or line.startswith("[mcp"):
        return EventLine(line, EVENT_STYLES["action"], "action")
    if kind == "ObservationEvent" or line.startswith("[observation"):
        return EventLine(line, EVENT_STYLES["observation"], "observation")
    if kind == "ConversationStateUpdateEvent" or line.startswith("[status]"):
        return EventLine(line, EVENT_STYLES["status"], "status")
    if line.startswith("[state]"):
        return EventLine(line, EVENT_STYLES["state"], "state")
    return EventLine(line, EVENT_STYLES["event"], "event")


def _duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {rest:.0f}s"
    hours, minutes = divmod(minutes, 60)
    return f"{int(hours)}h {int(minutes)}m"


def _clip(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _clip_multiline(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit].rstrip() + f"\n\n… clipped to {limit} chars …"


def _render_text_block(text: str, *, language: str = "markdown") -> Any:
    value = str(text or "")
    if language == "json":
        try:
            value = json.dumps(json.loads(value), ensure_ascii=False, indent=2, sort_keys=True)
        except Exception:
            pass
        return Syntax(value, "json", word_wrap=True)
    if value.lstrip().startswith("{") or value.lstrip().startswith("["):
        return Syntax(value, "json", word_wrap=True)
    if "\n" in value and ("#" in value or "- " in value or "```" in value):
        return Markdown(value)
    return Text(value)


def _render_prompt_digest(lines: list[str]) -> Any:
    if Table is None:
        return Text("\n".join(lines))
    table = Table(box=box.MINIMAL, expand=True, show_header=False, padding=(0, 1))
    table.add_column("Key", style="cyan", no_wrap=True, width=24)
    table.add_column("Value", style="white", ratio=3)
    if not lines:
        table.add_row("prompt", "full prompt hidden; no compact substitutions detected")
        return table
    for line in lines:
        if ":" in line and not line.lstrip().startswith("-"):
            key, value = line.split(":", 1)
            table.add_row(key.strip(), value.strip() or " ")
        else:
            table.add_row("•", line)
    return table


def _render_events(events: deque[Any]) -> Any:
    text = Text()
    if not events:
        text.append("No websocket events yet.", style="dim")
        return text
    for raw in list(events)[-5:]:
        if isinstance(raw, EventLine):
            text.append(raw.text, style=raw.style)
        else:
            text.append(str(raw), style="white")
        text.append("\n")
    return text


def _extract_prompt_dynamic_snippets(prompt: str) -> list[str]:
    text = str(prompt or "")
    snippets: list[str] = []
    patterns = [
        ("Original user task", r"Original user task:\s*(.*?)(?:\n\n|\n[A-Z][^\n]{0,80}:)"),
        ("Team Lead assignment", r"Team Lead assignment for this role run:\s*(.*?)(?:\n\n|\n[A-Z][^\n]{0,80}:)"),
        ("Validation profile", r"Validation profile[^\n]*:\s*(.*?)(?:\n\n[A-Z#]|\Z)"),
        ("Scout summary", r"Scout routing/status summary:\s*(.*?)(?:\n\n|\n[A-Z][^\n]{0,80}:)"),
        ("Research summary", r"Research routing/status summary:\s*(.*?)(?:\n\n|\n[A-Z][^\n]{0,80}:)"),
    ]
    for label, pattern in patterns:
        match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            snippets.append(f"{label}: {_clip(match.group(1), 500)}")
    if not snippets and text:
        snippets.append(f"prompt_size: {len(text)} chars hidden")
    return snippets


def _compact_dict(value: JsonDict, *, max_chars: int) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = str(value)
    return _clip(text, max_chars)


def _cap_lines(lines: list[str], *, max_chars: int) -> list[str]:
    out: list[str] = []
    total = 0
    for line in lines:
        if total + len(line) > max_chars:
            out.append(f"… compact prompt context clipped to {max_chars} chars …")
            break
        out.append(line)
        total += len(line)
    return out
