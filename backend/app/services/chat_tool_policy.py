"""Pure policy and protocol helpers for explicit phone-chat tools."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from typing import Any


SUPPORTED_IMAGE_RATIOS = ("1:1", "3:2", "16:9", "9:16")
ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[tuple[dict[str, Any], dict[str, Any]]]]


def _context_dependent_phrase(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", value).strip().lower()
    words = re.findall(r"[\w-]+", normalized, flags=re.UNICODE)
    return len(words) <= 6 and bool(re.search(
        r"\b(это|этот|эта|эту|эти|его|её|их|так|такое|выше|вложенн\w*)\b",
        normalized,
    ))


def required_search_arguments(
    messages: Sequence[Any], images: Sequence[str], provider_context: str = "",
) -> dict[str, Any]:
    latest = str(messages[-1].content).strip()
    if len(messages) == 1 and not images:
        query = latest
    else:
        lines = []
        for turn in messages:
            role = "Пользователь" if turn.role == "user" else "Ассистент"
            content = re.sub(r"\s+", " ", str(turn.content)).strip()
            lines.append(f"{role}: {content}")
        context = " ".join(lines)
        clarification = re.sub(r"\s+", " ", provider_context).strip()[:140]
        suffix = f" Уточнение модели: {clarification}" if clarification else ""
        prefix = "Найди сведения по контексту: "
        available = max(0, 500 - len(prefix) - len(suffix))
        query = f"{prefix}{context[-available:] if available else ''}{suffix}"
    return {"query": query.strip()[:500]}


def forced_search_model_arguments(
    messages: Sequence[Any], images: Sequence[str], arguments: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(arguments)
    query = re.sub(r"\s+", " ", str(normalized.get("query") or "")).strip()
    if not query or (_context_dependent_phrase(query) and (len(messages) > 1 or images)):
        normalized.update(required_search_arguments(messages, images, query))
    return normalized


def _aspect_ratio_state(messages: Sequence[Any]) -> tuple[set[str], set[str]]:
    patterns = (
        ("9:16", r"(?<!\d)9\s*(?::|/|x|х|на)\s*16(?!\d)"),
        ("16:9", r"(?<!\d)16\s*(?::|/|x|х|на)\s*9(?!\d)"),
        ("3:2", r"(?<!\d)3\s*(?::|/|x|х|на)\s*2(?!\d)"),
        ("1:1", r"(?<!\d)1\s*(?::|/|x|х|на)\s*1(?!\d)"),
        ("1:1", r"\b(?:квадрат\w*|square)\b"),
        ("9:16", r"\b(?:вертикаль\w*|сторис|reels|shorts)\b"),
        ("9:16", r"\bпортретн\w*\s+(?:ориентац\w*|формат\w*|кадр\w*)\b"),
        ("16:9", r"\b(?:горизонт\w*|широкоэкран\w*|landscape)\b"),
        ("16:9", r"\bальбомн\w*\s+(?:ориентац\w*|формат\w*|кадр\w*)\b"),
    )
    for turn in reversed(messages):
        if turn.role != "user":
            continue
        text = re.sub(r"\s+", " ", str(turn.content).lower())
        events: list[tuple[int, str, bool]] = []
        for ratio, pattern in patterns:
            for match in re.finditer(pattern, text):
                prefix = text[:match.start()]
                clause = re.split(r"[,;.!?]|\b(?:а|но|зато|but|rather|however)\b", prefix)[-1]
                rejected_before = re.search(
                    r"\b(?:(?:не|not)\s+(?:(?:совсем|точно|вообще|больше)\s+)?(?:(?:"
                    r"в|хоч\w*|нуж\w*|использ\w*|дела\w*|выбира\w*|формат\w*|want|need|use|choose|make"
                    r")\s+)?|(?:без|without)\s+)$",
                    clause,
                )
                suffix = text[match.end():]
                rejected_after = re.match(
                    r"\s*(?:[,;:.!?—-]\s*)?(?:(?:мне|нам)\s+)?(?:(?:точно|совсем|вообще|больше)\s+)?(?:"
                    r"не\s+(?:надо|нуж\w*|хоч\w*|подход\w*|использ\w*|делай|дела\w*|выбира\w*)|"
                    r"нет\b|(?:is\s+)?not\s+(?:needed|required|wanted|acceptable|desired|allowed)\b)",
                    suffix,
                )
                events.append((match.start(), ratio, bool(rejected_before or rejected_after)))
        if events:
            latest_by_ratio: dict[str, tuple[int, bool]] = {}
            for position, ratio, rejected in events:
                if ratio not in latest_by_ratio or position >= latest_by_ratio[ratio][0]:
                    latest_by_ratio[ratio] = (position, rejected)
            affirmative = {ratio for ratio, (_position, rejected) in latest_by_ratio.items() if not rejected}
            rejected = {ratio for ratio, (_position, is_rejected) in latest_by_ratio.items() if is_rejected}
            return affirmative, rejected
    return set(), set()


def explicit_image_aspect_ratio(messages: Sequence[Any]) -> str | None:
    affirmative, _rejected = _aspect_ratio_state(messages)
    return next(iter(affirmative)) if len(affirmative) == 1 else None


def requested_image_aspect_ratio(messages: Sequence[Any]) -> str:
    explicit = explicit_image_aspect_ratio(messages)
    if explicit:
        return explicit
    _affirmative, rejected = _aspect_ratio_state(messages)
    return next((ratio for ratio in SUPPORTED_IMAGE_RATIOS if ratio not in rejected), "1:1")


def required_image_arguments(
    messages: Sequence[Any], images: Sequence[str], provider_context: str = "",
) -> dict[str, Any]:
    latest = str(messages[-1].content).strip()
    if len(messages) == 1 and not images:
        prompt = latest
    else:
        lines = []
        for turn in messages:
            role = "Пользователь" if turn.role == "user" else "Ассистент"
            content = re.sub(r"\s+", " ", str(turn.content)).strip()
            lines.append(f"{role}: {content}")
        context = "\n".join(lines)
        clarification = re.sub(r"\s+", " ", provider_context).strip()[:600]
        suffix = f"\nУточнение после анализа контекста: {clarification}" if clarification else ""
        prefix = "Создай изображение по контексту разговора:\n"
        available = max(0, 3000 - len(prefix) - len(suffix))
        prompt = f"{prefix}{context[-available:] if available else ''}{suffix}"
    return {"prompt": prompt.strip()[:3000], "aspect_ratio": requested_image_aspect_ratio(messages)}


def forced_image_model_arguments(
    messages: Sequence[Any], images: Sequence[str], arguments: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(arguments)
    prompt = re.sub(r"\s+", " ", str(normalized.get("prompt") or "")).strip()
    if not prompt or (_context_dependent_phrase(prompt) and (len(messages) > 1 or images)):
        normalized.update(required_image_arguments(messages, images, prompt))
    explicit = explicit_image_aspect_ratio(messages)
    if explicit:
        normalized["aspect_ratio"] = explicit
    else:
        _affirmative, rejected = _aspect_ratio_state(messages)
        model_ratio = str(normalized.get("aspect_ratio") or "")
        if rejected and (model_ratio not in SUPPORTED_IMAGE_RATIOS or model_ratio in rejected):
            normalized["aspect_ratio"] = requested_image_aspect_ratio(messages)
    return normalized


def round_tools(tool_choice: str, used_tools: set[str], tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if tool_choice == "auto":
        return tools
    if tool_choice in used_tools:
        return []
    return [tool for tool in tools if tool.get("function", {}).get("name") == tool_choice]


def tool_allowed(tool_choice: str, name: str) -> bool:
    return tool_choice == "auto" or name == tool_choice


async def append_synthetic_tool_call(
    *, name: str, arguments: dict[str, Any], messages: list[dict[str, Any]],
    execute_tool: ToolExecutor, openrouter_style: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    call_id = f"call_{uuid.uuid4().hex[:12]}"
    result, provider_payload = await execute_tool(name, arguments)
    encoded: Any = json.dumps(arguments, ensure_ascii=False) if openrouter_style else arguments
    messages.append({
        "role": "assistant", "content": "",
        "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": encoded}}],
    })
    tool_message = {"role": "tool", "content": json.dumps(result, ensure_ascii=False)}
    tool_message["tool_call_id" if openrouter_style else "tool_name"] = call_id if openrouter_style else name
    messages.append(tool_message)
    return {"name": name, **result}, provider_payload


async def prime_required_tool(
    *, tool_choice: str, messages: list[dict[str, Any]], required_web_query: str,
    execute_tool: ToolExecutor, openrouter_style: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    if tool_choice in {"generate_image", "web_search"}:
        instruction = (
            "Пользователь явно выбрал создание изображения. Первым действием обязательно вызови "
            "generate_image. Сформируй самостоятельный подробный prompt по всей истории и содержимому "
            "прикреплённых изображений; сохрани явно указанный формат. Не отвечай текстом до вызова инструмента."
            if tool_choice == "generate_image" else
            "Пользователь явно выбрал поиск в интернете. Первым действием обязательно вызови web_search. "
            "Сформируй самостоятельный точный query по всей истории и содержимому прикреплённых изображений. "
            "Не отвечай текстом до вызова инструмента."
        )
        messages.insert(1, {"role": "system", "content": instruction})
        return [], [], set()
    if not required_web_query:
        return [], [], set()
    tool_run, provider_payload = await append_synthetic_tool_call(
        name="web_search", arguments={"query": required_web_query}, messages=messages,
        execute_tool=execute_tool, openrouter_style=openrouter_style,
    )
    return [tool_run], [provider_payload] if provider_payload else [], {"web_search"}
