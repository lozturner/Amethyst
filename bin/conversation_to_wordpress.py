#!/usr/bin/env python3
"""
Convert a ChatGPT conversation export JSON file into HTML that can be pasted into
WordPress' block editor.

The script attempts to support both the legacy `mapping`-based export format and
newer `messages` arrays by normalizing them into a chronological list of chat
messages before rendering them as HTML.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROLE_TITLES = {
    "assistant": "Assistant",
    "user": "User",
    "system": "System",
}


def load_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} does not contain valid JSON") from exc


def _load_json_from_zip(archive: zipfile.ZipFile) -> str:
    json_candidates = [
        name
        for name in archive.namelist()
        if name.lower().endswith(".json") and not name.endswith("/")
    ]
    if not json_candidates:
        raise ValueError("Zip archive does not include a JSON conversation file")

    # Prefer a single conversation.json style name, otherwise fall back to the
    # first JSON file in the archive.
    for preferred_name in ("conversation.json", "conversations.json"):
        for candidate in json_candidates:
            if Path(candidate).name == preferred_name:
                return candidate
    return json_candidates[0]


def load_conversation(path: Path, asset_dir: Optional[Path]) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Load conversation JSON data.

    When ``path`` is a zip archive, extract the JSON content and optionally
    unpack non-JSON attachments into ``asset_dir`` for use in rendered HTML.
    Returns a tuple of the parsed JSON data and a mapping of attachment keys to
    relative asset paths for later lookup when rendering.
    """

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as archive:
            json_member = _load_json_from_zip(archive)
            try:
                with archive.open(json_member) as handle:
                    data = json.load(handle)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path} does not contain valid JSON") from exc

            extracted: Dict[str, str] = {}
            if asset_dir:
                asset_dir.mkdir(parents=True, exist_ok=True)

            for member in archive.namelist():
                if member.endswith("/") or member == json_member:
                    continue
                if not asset_dir:
                    continue

                target_path = asset_dir / Path(member).name
                with archive.open(member) as source, target_path.open("wb") as target:
                    shutil.copyfileobj(source, target)

                relative = f"{asset_dir.name}/{target_path.name}" if asset_dir else target_path.name
                extracted[member] = relative
                extracted[target_path.name] = relative

            return data, extracted

    data = load_json(path)
    return data, {}


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, dict):
        return ""

    parts: List[str] = []
    if isinstance(content.get("parts"), list):
        for part in content["parts"]:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
    elif isinstance(content.get("text"), str):
        parts.append(content["text"])

    return "\n\n".join(part for part in parts if part)


def _message_timestamp(node: Dict[str, Any], message: Dict[str, Any]) -> float:
    created = message.get("create_time") or node.get("create_time")
    if created is None:
        return 0.0
    try:
        return float(created)
    except (TypeError, ValueError):
        return 0.0


def _normalize_role(raw_role: Optional[str]) -> str:
    if not raw_role:
        return "System"
    return ROLE_TITLES.get(raw_role.lower(), raw_role.title())


def _attachments_from_entry(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    attachments: List[Dict[str, Any]] = []
    for key in ("attachments", "files"):
        raw = entry.get(key) or entry.get("metadata", {}).get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, dict):
                attachments.append(item)
    return attachments


def _extract_from_mapping(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    for node in data.get("mapping", {}).values():
        message = node.get("message")
        if not message:
            continue

        role = _normalize_role(message.get("author", {}).get("role"))
        text = _text_from_content(message.get("content"))
        if not text:
            continue

        messages.append(
            {
                "role": role,
                "text": text,
                "created": _message_timestamp(node, message),
                "attachments": _attachments_from_entry(message),
            }
        )

    return sorted(messages, key=lambda msg: msg["created"])


def _extract_from_messages(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    for entry in data.get("messages", []):
        role = _normalize_role(entry.get("role") or entry.get("author", {}).get("role"))
        text = _text_from_content(entry.get("content"))
        if not text:
            continue

        created = entry.get("create_time") or entry.get("timestamp") or 0.0
        try:
            created_value = float(created)
        except (TypeError, ValueError):
            created_value = 0.0

        messages.append(
            {
                "role": role,
                "text": text,
                "created": created_value,
                "attachments": _attachments_from_entry(entry),
            }
        )

    return sorted(messages, key=lambda msg: msg["created"])


def extract_messages(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    if "mapping" in data:
        return _extract_from_mapping(data)
    if "messages" in data:
        return _extract_from_messages(data)
    raise ValueError("Conversation JSON is missing expected `mapping` or `messages` fields")


def _paragraphs_from_text(text: str) -> Iterable[str]:
    return [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]


def _render_paragraph(paragraph: str) -> str:
    escaped = html.escape(paragraph).replace("\n", "<br />")
    return f"<p>{escaped}</p>"


def _format_timestamp(created: float) -> Optional[str]:
    if not created:
        return None
    try:
        dt = _dt.datetime.fromtimestamp(created)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _resolve_attachment_path(entry: Dict[str, Any], assets: Dict[str, str]) -> Optional[str]:
    for key in ("file_path", "path", "id", "name", "filename"):
        value = entry.get(key)
        if not value:
            continue
        if value in assets:
            return assets[value]
        basename = Path(str(value)).name
        if basename in assets:
            return assets[basename]
    return None


def _render_attachments(attachments: List[Dict[str, Any]], assets: Dict[str, str]) -> str:
    rendered: List[str] = []
    for attachment in attachments:
        target = _resolve_attachment_path(attachment, assets)
        display_name = attachment.get("name") or attachment.get("filename") or attachment.get("file_name") or target
        safe_name = html.escape(display_name or "Attachment")
        mime_type = (attachment.get("mime_type") or attachment.get("content_type") or "").lower()

        if target and mime_type.startswith("image"):
            rendered.append(
                f"<figure class=\"chatgpt-attachment\"><img src=\"{html.escape(target)}\" alt=\"{safe_name}\" />"
                f"<figcaption>{safe_name}</figcaption></figure>"
            )
        elif target and mime_type.startswith("audio"):
            rendered.append(
                f"<div class=\"chatgpt-attachment\"><p>{safe_name}</p><audio controls src=\"{html.escape(target)}\"></audio></div>"
            )
        elif target:
            rendered.append(
                f"<p class=\"chatgpt-attachment\"><a href=\"{html.escape(target)}\">{safe_name}</a></p>"
            )
        elif display_name:
            rendered.append(f"<p class=\"chatgpt-attachment\">Attachment: {safe_name}</p>")
    return "\n".join(rendered)


def render_html(title: str, messages: List[Dict[str, Any]], assets: Dict[str, str]) -> str:
    now = _dt.datetime.now().strftime("%Y-%m-%d")
    heading = html.escape(title or "ChatGPT Conversation")
    header_block = f"<h2>{heading}</h2>\n<p><em>Published {now}</em></p>"

    rendered_messages: List[str] = []
    for message in messages:
        role_title = html.escape(message["role"])
        paragraphs = "\n".join(_render_paragraph(paragraph) for paragraph in _paragraphs_from_text(message["text"]))
        timestamp = _format_timestamp(message.get("created", 0.0))
        meta = f"<p class=\"chatgpt-meta\"><em>{timestamp}</em></p>" if timestamp else ""
        attachments = message.get("attachments") or []
        rendered_attachments = _render_attachments(attachments, assets) if attachments else ""

        rendered_messages.append(
            "\n".join(
                part
                for part in (
                    "<section class=\"chatgpt-message\">",
                    f"<h3>{role_title}</h3>",
                    meta,
                    paragraphs,
                    rendered_attachments,
                    "</section>",
                )
                if part
            )
        )

    body = "\n\n".join(rendered_messages)
    return f"{header_block}\n\n{body}\n"


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Path to conversation JSON export")
    parser.add_argument(
        "--title",
        default=None,
        help="Optional title to use for the WordPress post (defaults to JSON title or generic heading)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Optional file to write HTML output to (defaults to stdout)",
    )
    parser.add_argument(
        "--asset-dir",
        type=Path,
        default=None,
        help=(
            "Optional directory to extract attachments into when reading from a zip conversation export. "
            "Defaults to <input_stem>_assets when the input is a zip file."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    asset_dir = args.asset_dir
    if asset_dir is None and args.input.suffix.lower() == ".zip":
        asset_dir = Path.cwd() / f"{args.input.stem}_assets"

    data, assets = load_conversation(args.input, asset_dir)

    messages = extract_messages(data)
    if not messages:
        raise ValueError("Conversation file did not contain any chat messages to render")

    title = args.title or data.get("title") or "ChatGPT Conversation"
    html_output = render_html(title, messages, assets)

    if args.output:
        args.output.write_text(html_output, encoding="utf-8")
    else:
        sys.stdout.write(html_output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
