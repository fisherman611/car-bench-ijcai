#!/usr/bin/env python3
"""LLM-backed 3-way task router for CAR-bench analyzer experiments.

The analyzer only looks at the user question and visible tool environment, then
routes to base, hallucination, or disambiguation. It does not solve the task and
does not infer hidden tools. Use ``--mode heuristic`` for offline smoke tests.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TASKS = ("base", "hallucination", "disambiguation")
DEFAULT_ANALYZER_MODEL = "nvidia_nim/nvidia/meta/llama-3.1-70b-instruct"

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "could",
    "do",
    "does",
    "for",
    "from",
    "get",
    "give",
    "help",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "please",
    "set",
    "show",
    "tell",
    "that",
    "the",
    "this",
    "to",
    "turn",
    "what",
    "with",
    "you",
}

ACTION_WORDS = {
    "add",
    "adjust",
    "call",
    "change",
    "close",
    "delete",
    "find",
    "navigate",
    "open",
    "replace",
    "search",
    "send",
    "set",
    "start",
    "turn",
}

INFO_WORDS = {
    "am",
    "are",
    "current",
    "do",
    "does",
    "how",
    "is",
    "status",
    "tell",
    "what",
    "when",
    "where",
    "which",
}

AMBIGUOUS_REFERENCES = {"it", "that", "this", "there", "one", "them"}

SYNONYMS = {
    "ac": {"air", "conditioning", "climate"},
    "aircon": {"air", "conditioning", "climate"},
    "conditioner": {"air", "conditioning", "climate"},
    "temperature": {"temp", "climate"},
    "temp": {"temperature", "climate"},
    "ev": {"electric", "vehicle", "charging", "charger"},
    "charger": {"charging", "station"},
    "chargers": {"charging", "station"},
    "nearby": {"near", "search", "poi"},
    "route": {"navigation", "navigate"},
    "directions": {"navigation", "route"},
    "navigate": {"navigation", "route"},
    "sunshade": {"shade"},
    "shade": {"sunshade"},
    "sunroof": {"roof"},
    "fog": {"light", "lights"},
    "headlight": {"light", "lights"},
    "headlights": {"light", "lights"},
    "battery": {"charging", "soc", "range"},
    "health": {"condition", "status"},
    "percent": {"percentage"},
    "fully": {"percentage"},
}

FIELD_HINTS = {
    "percentage": {"percent", "percentage", "%", "half", "fully", "full"},
    "temperature": {"temperature", "temp", "degrees", "degree", "celsius"},
    "level": {"level", "speed"},
    "zone": {"driver", "passenger", "rear", "front", "left", "right", "seat", "zone"},
    "location": {"location", "city", "nearby", "near", "destination"},
    "route_id": {"route", "waypoint", "destination"},
    "contact": {"contact", "person", "phone", "email"},
    "message": {"message", "email", "send"},
    "health": {"health"},
}


def load_runtime_env() -> None:
    """Load local env vars and route NVIDIA NIM calls through 9router when configured."""
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
    except Exception:
        pass

    ninerouter_key = os.getenv("NINEROUTER_API_KEY")
    ninerouter_base = os.getenv("NINEROUTER_API_BASE")

    if ninerouter_key:
        os.environ["NVIDIA_NIM_API_KEY"] = ninerouter_key
    if ninerouter_base:
        os.environ["NVIDIA_NIM_API_BASE"] = ninerouter_base


@dataclass
class VisibleTool:
    name: str
    description: str
    parameters: dict[str, Any]
    result_schema: dict[str, Any]

    @property
    def parameter_names(self) -> set[str]:
        return _schema_property_names(self.parameters)

    @property
    def result_names(self) -> set[str]:
        return _schema_property_names(self.result_schema)

    @property
    def required_names(self) -> set[str]:
        required = self.parameters.get("required", [])
        return {str(item).lower() for item in required if isinstance(item, str)}

    @property
    def vocabulary(self) -> set[str]:
        text = " ".join(
            [
                self.name,
                self.description,
                " ".join(self.parameter_names),
                " ".join(self.result_names),
            ]
        )
        return expand_tokens(tokenize(text))


def tokenize(text: str) -> set[str]:
    raw = re.findall(r"[a-zA-Z0-9_%]+", text.lower().replace("_", " "))
    return {token for token in raw if token and token not in STOPWORDS}


def expand_tokens(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    for token in list(tokens):
        expanded.update(SYNONYMS.get(token, set()))
    return expanded


def _schema_property_names(schema: dict[str, Any]) -> set[str]:
    names: set[str] = set()

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        props = node.get("properties")
        if isinstance(props, dict):
            for name, child in props.items():
                names.update(tokenize(str(name)))
                walk(child)
        items = node.get("items")
        if isinstance(items, dict):
            walk(items)

    walk(schema)
    return names


def _load_json_field(raw: Any, field_name: str) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{field_name} must decode to a JSON object")
        return parsed
    raise ValueError(f"{field_name} must be a JSON object or JSON string")


def load_case(path: Path) -> dict[str, Any]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    case = data.get("case", {})
    tools = []
    for raw_tool in data.get("visible_tools", []):
        tools.append(
            VisibleTool(
                name=str(raw_tool.get("name", "")),
                description=str(raw_tool.get("description", "")),
                parameters=_load_json_field(raw_tool.get("parameters_json"), "parameters_json"),
                result_schema=_load_json_field(raw_tool.get("result_schema_json"), "result_schema_json"),
            )
        )
    return {
        "path": str(path),
        "name": case.get("name", path.stem),
        "expected_task": case.get("expected_task"),
        "user_question": str(case.get("user_question", "")),
        "visible_tools": tools,
    }


def tool_to_payload(tool: VisibleTool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
        "result_schema": tool.result_schema,
    }


def capability_coverage(user_question: str, tools: list[VisibleTool]) -> tuple[float, VisibleTool | None]:
    user_tokens = expand_tokens(tokenize(user_question))
    if not user_tokens or not tools:
        return 0.0, None

    best_score = 0.0
    best_tool = None
    intent_tokens = user_tokens - ACTION_WORDS
    if not intent_tokens:
        intent_tokens = user_tokens

    for tool in tools:
        vocab = tool.vocabulary
        overlap = intent_tokens & vocab
        coverage = len(overlap) / max(1, min(len(intent_tokens), len(vocab)))

        # Give a small boost when the tool name directly contains an important user token.
        tool_name_tokens = expand_tokens(tokenize(tool.name))
        name_overlap = len(intent_tokens & tool_name_tokens) / max(1, min(len(intent_tokens), len(tool_name_tokens)))
        score = min(1.0, coverage * 0.75 + name_overlap * 0.25)

        if score > best_score:
            best_score = score
            best_tool = tool

    return round(best_score, 3), best_tool


def user_information_completeness(user_question: str, candidate: VisibleTool | None) -> float:
    text = user_question.lower()
    tokens = tokenize(text)

    if re.search(
        r"\b(open|close|set|adjust|turn|delete|replace|start|stop|change)\s+"
        r"(it|that|this|one|them)\b",
        text,
    ):
        return 0.2

    if tokens & AMBIGUOUS_REFERENCES and len(tokens - AMBIGUOUS_REFERENCES - ACTION_WORDS) <= 1:
        return 0.2

    if re.search(r"\b(set|change|adjust)\b.*\b(temp|temperature|climate)\b", text):
        if not re.search(r"\d", text):
            return 0.25

    if re.search(r"\b(open|close|adjust|set)\b.*\b(window|sunroof|sunshade|shade|roof)\b", text):
        # Specific percentages are often required for "set/adjust/open" requests.
        has_amount = bool(re.search(r"\d|percent|percentage|fully|full|half|all the way", text))
        if not has_amount and "close" not in text:
            return 0.45

    if candidate is not None:
        # If a required parameter is not mentioned and is not usually inferable,
        # treat this as user-side incompleteness.
        user_expanded = expand_tokens(tokens)
        missing_required = []
        for param in candidate.required_names:
            param_tokens = expand_tokens(tokenize(param))
            if not (param_tokens & user_expanded):
                missing_required.append(param)
        if missing_required:
            # Do not over-penalize tools whose required params are generic IDs
            # usually obtained through tool calls.
            non_id_missing = [
                p
                for p in missing_required
                if not any(id_word in p for id_word in ("id", "route", "location"))
            ]
            if non_id_missing and not re.search(r"\d", text):
                return 0.55

    return 1.0


def _requested_field_hints(user_question: str) -> set[str]:
    text = user_question.lower()
    tokens = expand_tokens(tokenize(text))
    hints = set()
    for field, words in FIELD_HINTS.items():
        if tokens & words or any(word in text for word in words):
            hints.add(field)
    if "%" in user_question:
        hints.add("percentage")
    return hints


def schema_result_sufficiency(user_question: str, candidate: VisibleTool | None) -> float:
    if candidate is None:
        return 0.8

    text = user_question.lower()
    tokens = expand_tokens(tokenize(text))
    param_tokens = expand_tokens(candidate.parameter_names)
    result_tokens = expand_tokens(candidate.result_names)
    hints = _requested_field_hints(user_question)

    is_info_request = "?" in user_question or bool(tokens & INFO_WORDS) and not bool(tokens & ACTION_WORDS)
    missing = []

    if is_info_request:
        required_result_hints = hints - {"percentage"}
        for hint in required_result_hints:
            hint_tokens = expand_tokens(tokenize(hint))
            if not (hint_tokens & result_tokens):
                missing.append(f"result_{hint}")

        needed = (tokens - INFO_WORDS - ACTION_WORDS - STOPWORDS) | hints
        needed = {t for t in needed if len(t) > 2}
        if needed and not (needed & result_tokens):
            missing.append("result_field")
    else:
        for hint in hints:
            hint_tokens = expand_tokens(tokenize(hint))
            if hint == "zone":
                if not ({"zone", "seat", "window", "driver", "passenger", "rear", "front"} & param_tokens):
                    missing.append(hint)
            elif not (hint_tokens & param_tokens):
                missing.append(hint)

    if missing:
        return 0.25

    if candidate.parameters and candidate.required_names:
        # The schema itself exposes required parameters, so it is sufficient.
        return 0.95

    if is_info_request and result_tokens:
        return 0.95

    return 0.85


def route_case(user_question: str, tools: list[VisibleTool]) -> dict[str, Any]:
    c_score, candidate = capability_coverage(user_question, tools)
    u_score = user_information_completeness(user_question, candidate)
    r_score = schema_result_sufficiency(user_question, candidate)
    env_score = c_score * r_score

    scores = {
        "base": env_score * u_score,
        "hallucination": (1 - env_score) * u_score,
        "disambiguation": 1 - u_score,
    }

    # Deterministic tie-breaks: missing user info first, then environment
    # insufficiency, then normal base.
    ordered = sorted(
        scores.items(),
        key=lambda item: (item[1], {"disambiguation": 2, "hallucination": 1, "base": 0}[item[0]]),
        reverse=True,
    )
    task = ordered[0][0]

    return {
        "task": task,
        "scores": {key: round(value, 4) for key, value in scores.items()},
        "signals": {
            "C": round(c_score, 3),
            "U": round(u_score, 3),
            "R": round(r_score, 3),
            "E": round(env_score, 3),
            "candidate_tool": candidate.name if candidate else None,
        },
        "ranking": [{"task": key, "score": round(value, 4)} for key, value in ordered],
    }


def analyzer_system_prompt() -> str:
    return """You are a task Analyzer for a CAR-bench tool-use benchmark.

Given:
- a user question
- visible tools
- visible parameter schemas
- visible result schemas

Route the example into exactly one of three task types:

1. base:
The request can be fulfilled with the visible tools. The user provides enough information, and the visible schemas/result fields are sufficient.

2. hallucination:
The user request is clear enough, but the visible tool environment is insufficient. This includes no suitable visible tool, missing visible parameters, missing visible prerequisite capability, or missing visible result fields.

3. disambiguation:
The user request is ambiguous or lacks necessary user-provided information.

Use these internal signals:
- C: capability coverage
- U: user information completeness
- R: schema/result sufficiency
- E = C * R

Task scores:
- P(base) = E * U
- P(hallucination) = (1 - E) * U
- P(disambiguation) = 1 - U

Important rules:
- Do not infer, name, or rely on hidden tools.
- Only use the visible tools and schemas.
- If the issue is caused by missing user information, choose disambiguation.
- If the issue is caused by insufficient visible tool environment and the user request is clear, choose hallucination.
- Do not solve the task, call tools, or write a user response.

Output only a JSON object with this shape:
{
  "task": "base | hallucination | disambiguation",
  "signals": {"C": 0.0, "U": 0.0, "R": 0.0, "E": 0.0},
  "scores": {"base": 0.0, "hallucination": 0.0, "disambiguation": 0.0},
  "reason": "one short sentence"
}
"""


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    candidates = [stripped]
    match = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL | re.IGNORECASE)
    if match:
        candidates.insert(0, match.group(1).strip())

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(stripped[start : end + 1])

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"Analyzer LLM did not return a JSON object: {text[:500]}")


def _normalize_llm_prediction(payload: dict[str, Any], *, raw_text: str, model: str) -> dict[str, Any]:
    task = str(payload.get("task", "")).strip().lower()
    if task not in TASKS:
        raise ValueError(f"Analyzer LLM returned invalid task {task!r}: {raw_text[:500]}")

    def number_map(value: Any, keys: tuple[str, ...]) -> dict[str, float]:
        if not isinstance(value, dict):
            return {}
        normalized = {}
        for key in keys:
            try:
                normalized[key] = round(float(value.get(key, 0.0)), 4)
            except (TypeError, ValueError):
                normalized[key] = 0.0
        return normalized

    signals = number_map(payload.get("signals"), ("C", "U", "R", "E"))
    scores = number_map(payload.get("scores"), TASKS)
    ranking = [
        {"task": key, "score": value}
        for key, value in sorted(scores.items(), key=lambda item: item[1], reverse=True)
    ]
    return {
        "task": task,
        "scores": scores,
        "signals": signals,
        "ranking": ranking,
        "reason": str(payload.get("reason", "")).strip(),
        "mode": "llm",
        "model": model,
    }


def route_case_llm(
    user_question: str,
    tools: list[VisibleTool],
    *,
    model: str,
    temperature: float,
) -> dict[str, Any]:
    load_runtime_env()

    try:
        from litellm import completion
    except ImportError as exc:
        raise RuntimeError(
            "LLM mode requires litellm. Install the track-1-agent extra or run with --mode heuristic."
        ) from exc

    user_payload = {
        "user_question": user_question,
        "visible_tools": [tool_to_payload(tool) for tool in tools],
    }
    response = completion(
        model=model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": analyzer_system_prompt()},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
        ],
    )
    text = response.choices[0].message.content or ""
    payload = _extract_json_object(text)
    return _normalize_llm_prediction(payload, raw_text=text, model=model)


def iter_case_paths(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(path.glob("*.toml"))
    return [path]


def main() -> int:
    load_runtime_env()

    parser = argparse.ArgumentParser(description="Route analyzer TOML cases into base/hallucination/disambiguation.")
    parser.add_argument("path", type=Path, help="Analyzer case TOML file or directory of TOML files.")
    parser.add_argument(
        "--mode",
        choices=("llm", "heuristic"),
        default="llm",
        help="Analyzer backend. Default: llm.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("ANALYZER_LLM") or os.getenv("AGENT_LLM") or DEFAULT_ANALYZER_MODEL,
        help="LiteLLM model for --mode llm. Can also be set with ANALYZER_LLM.",
    )
    parser.add_argument("--temperature", type=float, default=0.0, help="LLM analyzer temperature.")
    parser.add_argument("--check", action="store_true", help="Fail if a case has expected_task and prediction differs.")
    args = parser.parse_args()

    outputs = []
    failures = []
    for case_path in iter_case_paths(args.path):
        case = load_case(case_path)
        if args.mode == "llm":
            prediction = route_case_llm(
                case["user_question"],
                case["visible_tools"],
                model=args.model,
                temperature=args.temperature,
            )
        else:
            prediction = route_case(case["user_question"], case["visible_tools"])
            prediction["mode"] = "heuristic"
        output = {
            "case": case["name"],
            "path": case["path"],
            "expected_task": case["expected_task"],
            **prediction,
        }
        outputs.append(output)
        if args.check and case["expected_task"] and case["expected_task"] != prediction["task"]:
            failures.append(output)

    if args.path.is_dir():
        print(json.dumps(outputs, indent=2, ensure_ascii=False))
    else:
        print(json.dumps(outputs[0], indent=2, ensure_ascii=False))

    if failures:
        print(f"\nAnalyzer route check failed for {len(failures)} case(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
