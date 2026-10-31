#!/usr/bin/env python3
"""Parse one scanned page with an image-capable chat API.

The provider must speak the OpenAI-compatible /chat/completions protocol and
accept image_url data URLs. Works with Google AI Studio (Gemini), OpenRouter,
Groq, and local vLLM/LM Studio endpoints.

Environment:
    PAGE_AI_BASE_URL   default https://generativelanguage.googleapis.com/v1beta/openai
    PAGE_AI_API_KEY    required for hosted providers
    PAGE_AI_MODEL      required, e.g. gemini-2.5-flash or a free OpenRouter model
    PAGE_AI_TIMEOUT    seconds, default 180
    PAGE_AI_MAX_TOKENS max output tokens, default 8192
    PAGE_AI_JSON_MODE  set to 1 to request response_format=json_object
    PAGE_AI_EXTRA_HEADERS
                       optional JSON object of extra request headers.
                       Example for OmniRoute:
                       {"x-omniroute-compression":"off","X-OmniRoute-No-Cache":"true"}

Usage:
    python3 scripts/parse_page.py --section genealogy --page 25
    python3 scripts/parse_page.py --section genealogy --page 25 --dry-run
    python3 scripts/parse_page.py --section genealogy --page 25 --force --ocr
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from common import (
    ROOT,
    atomic_write_json,
    atomic_write_text,
    find_row,
    load_json,
    meta_path,
    ocr_path,
    parsed_path,
    prompt_path,
    resolve_image,
)
from prompt import build_messages, schema_text
from validate_page import validate

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
RETRYABLE = {429, 500, 502, 503, 504}


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def mime_for(path: Path) -> str:
    return "image/png" if path.suffix.lower() == ".png" else "image/jpeg"


def image_data_url(path: Path) -> str:
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_for(path)};base64,{payload}"


def strip_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return text


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        log(f"  {name} 값이 정수가 아닙니다: {raw!r}. 기본값 {default} 사용")
        return default


def extra_headers() -> dict[str, str]:
    raw = os.environ.get("PAGE_AI_EXTRA_HEADERS", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log(f"  PAGE_AI_EXTRA_HEADERS 무시: {exc}")
        return {}
    if not isinstance(data, dict):
        log("  PAGE_AI_EXTRA_HEADERS 무시: JSON 객체가 아닙니다.")
        return {}
    return {str(key): str(value) for key, value in data.items()}


def content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text" and part.get("text"):
                    parts.append(str(part["text"]))
                elif part.get("text"):
                    parts.append(str(part["text"]))
        return "\n".join(parts)
    return str(content)


def call_api(messages: list[dict], image_path: Path, model: str) -> tuple[str, dict, dict]:
    base_url = os.environ.get("PAGE_AI_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    api_key = os.environ.get("PAGE_AI_API_KEY", "")
    timeout = float(os.environ.get("PAGE_AI_TIMEOUT", "180"))
    max_tokens = env_int("PAGE_AI_MAX_TOKENS", 8192)

    # Inject the image into the user message for providers with vision support.
    prepared = [dict(message) for message in messages]
    for message in prepared:
        if message["role"] == "user":
            message["content"] = [
                {"type": "text", "text": str(message["content"])},
                {"type": "image_url", "image_url": {"url": image_data_url(image_path)}},
            ]
            break

    body: dict = {
        "model": model,
        "messages": prepared,
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    if os.environ.get("PAGE_AI_JSON_MODE") == "1":
        body["response_format"] = {"type": "json_object"}

    headers = {
        **extra_headers(),
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                route_headers = {
                    key.lower(): value
                    for key, value in response.headers.items()
                    if key.lower().startswith("x-omniroute-")
                }
            message = payload["choices"][0]["message"]
            text = content_text(message.get("content"))
            usage = payload.get("usage", {})
            response_meta = {
                "response_model": payload.get("model") or model,
                "omniroute": route_headers,
            }
            return text, usage, response_meta
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:800]
            last_error = RuntimeError(f"HTTP {exc.code}: {detail}")
            if exc.code not in RETRYABLE:
                raise last_error from exc
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            last_error = exc
        if attempt < 3:
            delay = 2 ** attempt
            log(f"  API 오류, {delay}초 후 재시도 ({attempt}/3): {last_error}")
            time.sleep(delay)
    raise RuntimeError(f"API 호출 실패: {last_error}")


def parse_page(
    section: str,
    page_no: int,
    *,
    force: bool = False,
    dry_run: bool = False,
    use_ocr: bool = False,
    out: Path | None = None,
    model: str | None = None,
) -> dict | None:
    row = find_row(section, page_no)
    if row is None:
        raise SystemExit(f"{section} {page_no}면이 manifest에 없습니다.")
    if row["page_type"] == "missing":
        raise SystemExit(f"{section} {page_no}면은 미수록 페이지입니다.")

    destination = out or parsed_path(section, page_no)
    if destination.exists() and not force and not dry_run:
        log(f"SKIP {section} {page_no}: 이미 {display_path(destination)}가 있습니다. --force로 덮어쓰세요.")
        existing = load_json(destination)
        return existing if isinstance(existing, dict) else None

    image = resolve_image(row)
    if image is None:
        raise SystemExit(f"{section} {page_no}면 이미지 파일을 찾지 못했습니다: {row.get('source_path')}")

    ocr_text = None
    if use_ocr:
        path = ocr_path(section, page_no)
        if not path.exists():
            raise SystemExit(f"OCR 파일이 없습니다: {path.relative_to(ROOT)}. 먼저 scripts/ocr.py를 실행하세요.")
        ocr_text = path.read_text(encoding="utf-8")

    messages = build_messages(
        section=section,
        page_no=page_no,
        page_type_hint=row["page_type"],
        width=row.get("width"),
        height=row.get("height"),
        image_path=row["normalized_path"] or row["source_path"],
        ocr_text=ocr_text,
        notes=row.get("notes"),
    )

    if dry_run:
        destination = prompt_path(section, page_no)
        atomic_write_text(destination, f"[system]\n{messages[0]['content']}\n\n[user]\n{messages[1]['content']}\n")
        log(f"DRY  {section} {page_no}: {destination.relative_to(ROOT)}")
        return None

    model = model or os.environ.get("PAGE_AI_MODEL", "")
    if not model:
        raise SystemExit("PAGE_AI_MODEL 환경변수를 지정하세요. (예: gemini-2.5-flash)")
    if not os.environ.get("PAGE_AI_API_KEY"):
        raise SystemExit("PAGE_AI_API_KEY 환경변수를 지정하세요. 로컬 서버면 더미 값을 넣어도 됩니다.")

    log(f"AI   {section} {page_no}: {image.relative_to(ROOT)} ({model})")
    started = time.time()
    text, usage, response_meta = call_api(messages, image, model)
    response_models = [response_meta.get("response_model", model)]
    routing_traces = [response_meta.get("omniroute", {})]
    first_raw = text
    try:
        data = json.loads(strip_json(text))
    except json.JSONDecodeError as exc:
        # One correction attempt with the parser error.
        log(f"  JSON 파싱 실패, 교정 요청: {exc}")
        first_raw_path = destination.with_name(destination.stem + ".raw.first.txt")
        atomic_write_text(first_raw_path, first_raw)
        log(f"  첫 응답 저장: {display_path(first_raw_path)}")
        messages = messages + [
            {"role": "assistant", "content": text},
            {
                "role": "user",
                "content": (
                    f"위 출력은 JSON 파싱에 실패했다: {exc}. "
                    "설명, 마크다운, 코드펜스 없이 올바른 JSON 객체 하나만 다시 출력하라. "
                    "문자열 안의 따옴표는 이스케이프하고, 후행 쉼표를 쓰지 마라."
                ),
            },
        ]
        try:
            text, usage2, response_meta = call_api(messages, image, model)
        except Exception as call_exc:
            raise SystemExit(f"교정 호출 실패: {call_exc}")
        response_models.append(response_meta.get("response_model", model))
        routing_traces.append(response_meta.get("omniroute", {}))
        usage = {"first": usage, "second": usage2}
        try:
            data = json.loads(strip_json(text))
        except json.JSONDecodeError as exc2:
            raw_path = destination.with_name(destination.stem + ".raw.txt")
            atomic_write_text(raw_path, text)
            meta = {
                "section": section,
                "printed_page_no": page_no,
                "model": model,
                "requested_model": model,
                "response_models": response_models,
                "omniroute": routing_traces,
                "base_url": os.environ.get("PAGE_AI_BASE_URL", DEFAULT_BASE_URL),
                "image": str(image.relative_to(ROOT)),
                "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                "parsed_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(time.time() - started, 2),
                "usage": usage,
                "json_error": str(exc2),
                "first_json_error": str(exc),
                "raw_output": display_path(raw_path),
            }
            atomic_write_json(meta_path(section, page_no), meta)
            raise SystemExit(
                f"JSON 파싱 실패: {exc2}\\n"
                f"첫 응답: {display_path(first_raw_path)}\\n"
                f"교정 응답: {display_path(raw_path)}\\n"
                f"meta: {display_path(meta_path(section, page_no))}"
            )

    errors, warnings = validate(data, section, page_no)
    if errors:
        log(f"  검증 오류 {len(errors)}건, 교정 요청")
        messages = messages + [
            {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)},
            {
                "role": "user",
                "content": "다음 검증 오류를 고쳐 JSON 전체를 다시 출력하라. 설명은 쓰지 않는다.\n- "
                + "\n- ".join(errors),
            },
        ]
        text, usage2, response_meta = call_api(messages, image, model)
        response_models.append(response_meta.get("response_model", model))
        routing_traces.append(response_meta.get("omniroute", {}))
        try:
            data = json.loads(strip_json(text))
        except json.JSONDecodeError as exc2:
            raw_path = destination.with_name(destination.stem + ".raw.validation.txt")
            atomic_write_text(raw_path, text)
            meta = {
                "section": section,
                "printed_page_no": page_no,
                "model": model,
                "requested_model": model,
                "response_models": response_models,
                "omniroute": routing_traces,
                "base_url": os.environ.get("PAGE_AI_BASE_URL", DEFAULT_BASE_URL),
                "image": str(image.relative_to(ROOT)),
                "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                "parsed_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_seconds": round(time.time() - started, 2),
                "usage": usage,
                "json_error": str(exc2),
                "raw_output": display_path(raw_path),
            }
            atomic_write_json(meta_path(section, page_no), meta)
            raise SystemExit(
                f"검증 교정 JSON 파싱 실패: {exc2}\\n"
                f"응답: {display_path(raw_path)}\\n"
                f"meta: {display_path(meta_path(section, page_no))}"
            )
        usage = {"first": usage, "second": usage2}
        errors, warnings = validate(data, section, page_no)
        if errors:
            log(f"  교정 후에도 오류 {len(errors)}건. needs_human으로 저장합니다.")
            data.setdefault("page", {})["quality"] = {
                **data.get("page", {}).get("quality", {}),
                "needs_human": True,
            }

    for warning in warnings:
        log(f"  ! {warning}")

    atomic_write_json(destination, data)
    meta = {
        "section": section,
        "printed_page_no": page_no,
        "model": model,
        "requested_model": model,
        "response_models": response_models,
        "omniroute": routing_traces,
        "base_url": os.environ.get("PAGE_AI_BASE_URL", DEFAULT_BASE_URL),
        "image": str(image.relative_to(ROOT)),
        "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "schema_sha256": hashlib.sha256(schema_text().encode("utf-8")).hexdigest(),
        "parsed_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(time.time() - started, 2),
        "usage": usage,
        "validation_errors": errors,
        "validation_warnings": warnings,
    }
    atomic_write_json(meta_path(section, page_no), meta)
    log(f"SAVE {section} {page_no}: {display_path(destination)}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--section", required=True, choices=["frontmatter", "genealogy"])
    parser.add_argument("--page", required=True, type=int)
    parser.add_argument("--force", action="store_true", help="기존 결과를 덮어쓴다")
    parser.add_argument("--dry-run", action="store_true", help="프롬프트만 저장하고 API는 호출하지 않는다")
    parser.add_argument("--ocr", action="store_true", help="OCR 텍스트를 보조 자료로 함께 넣는다")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--model")
    args = parser.parse_args()
    parse_page(
        args.section,
        args.page,
        force=args.force,
        dry_run=args.dry_run,
        use_ocr=args.ocr,
        out=args.out,
        model=args.model,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
