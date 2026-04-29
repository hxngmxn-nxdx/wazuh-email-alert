#!/usr/bin/env python3
"""Render and send styled Wazuh alert e-mails through local sendmail/Postfix."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


TEMPLATE_PATH = Path(__file__).parent / "templates" / "wazuh_alert_template.html"
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
TIMESTAMP_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(?:Z|[+-]\d{2}:?\d{2})?$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate HTML alert cards from Wazuh JSON and send through Postfix sendmail."
    )
    parser.add_argument(
        "--input",
        default="-",
        help='Path to alert JSON (use "-" to read from stdin).',
    )
    parser.add_argument(
        "--to",
        dest="to_addr",
        default=os.getenv("WAZUH_MAIL_TO"),
        help="Recipient e-mail address (or WAZUH_MAIL_TO env var).",
    )
    parser.add_argument(
        "--from",
        dest="from_addr",
        default=os.getenv("WAZUH_MAIL_FROM", "wazuh@localhost"),
        help="Sender e-mail address (default: wazuh@localhost).",
    )
    parser.add_argument(
        "--subject-prefix",
        default="Wazuh notification",
        help='Subject prefix before dynamic context (default: "Wazuh notification").',
    )
    parser.add_argument(
        "--sendmail",
        default="/usr/sbin/sendmail",
        help="Path to sendmail binary (default: /usr/sbin/sendmail).",
    )
    parser.add_argument(
        "--output-html",
        help="Optional path to write rendered HTML (for preview/debug).",
    )
    parser.add_argument(
        "--output-eml",
        help="Optional path to write MIME message (.eml).",
    )
    parser.add_argument(
        "--output-text",
        help="Optional path to write plain-text fallback body.",
    )
    parser.add_argument(
        "--no-send",
        action="store_true",
        help="Render files but do not send the e-mail.",
    )
    return parser.parse_args()


def read_input(path: str) -> str:
    if path == "-":
        data = sys.stdin.read()
    else:
        data = Path(path).read_text(encoding="utf-8")
    if not data.strip():
        raise ValueError("Alert input is empty.")
    return data


def load_alert_json(raw_data: str) -> Dict[str, Any]:
    payload = json.loads(raw_data)
    if isinstance(payload, dict) and isinstance(payload.get("_source"), dict):
        return payload["_source"]
    if isinstance(payload, dict):
        return payload
    raise ValueError("Expected alert payload to be a JSON object.")


def get_path(data: Dict[str, Any], path: str, default: Any = "-") -> Any:
    current: Any = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current if current not in (None, "", []) else default


def as_string(value: Any, default: str = "-") -> str:
    if value in (None, "", []):
        return default
    if isinstance(value, list):
        return ", ".join(as_string(item, default="") for item in value if item is not None) or default
    return str(value)


def parse_level(value: Any) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def severity_palette(level: int) -> Dict[str, str]:
    if level >= 16:
        return {"label": "Critical", "bg": "#5a189a", "text": "#f8f5ff"}
    if level == 15:
        return {"label": "High", "bg": "#0d47a1", "text": "#eff6ff"}
    if level == 14:
        return {"label": "High", "bg": "#1565c0", "text": "#eff6ff"}
    if level == 13:
        return {"label": "High", "bg": "#1976d2", "text": "#eff6ff"}
    if level == 12:
        return {"label": "High", "bg": "#1e88e5", "text": "#eff6ff"}
    if level >= 10:
        return {"label": "High", "bg": "#2196f3", "text": "#eff6ff"}
    if level >= 7:
        return {"label": "Medium", "bg": "#1d4ed8", "text": "#eff6ff"}
    if level >= 4:
        return {"label": "Low", "bg": "#2563eb", "text": "#eff6ff"}
    return {"label": "Info", "bg": "#334155", "text": "#f8fafc"}


def flatten_dict(data: Any, prefix: str = "") -> List[Tuple[str, str]]:
    flat: List[Tuple[str, str]] = []
    if isinstance(data, dict):
        for key in sorted(data.keys()):
            child_prefix = f"{prefix}.{key}" if prefix else key
            flat.extend(flatten_dict(data[key], child_prefix))
        return flat
    if isinstance(data, list):
        if not data:
            flat.append((prefix, "-"))
            return flat
        if all(not isinstance(item, (dict, list)) for item in data):
            flat.append((prefix, ", ".join(as_string(item, default="") for item in data)))
            return flat
        for idx, item in enumerate(data):
            child_prefix = f"{prefix}[{idx}]"
            flat.extend(flatten_dict(item, child_prefix))
        return flat
    flat.append((prefix, as_string(data)))
    return flat


def normalize_message(raw_message: str) -> str:
    text = raw_message.strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    return text.replace("\r\n", "\n").strip()


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 16] + "\n\n...[truncated]"


def html_escape(value: Any) -> str:
    return html.escape(as_string(value))


def format_timestamp_display(value: Any) -> str:
    text = as_string(value)
    if text == "-":
        return text
    match = TIMESTAMP_RE.match(text.strip())
    if not match:
        return text
    date_part, time_part, fraction = match.groups()
    if fraction:
        fraction = fraction.rstrip("0")
        if len(fraction) > 3:
            fraction = fraction[:3]
    if fraction:
        return f"{date_part} {time_part}.{fraction}"
    return f"{date_part} {time_part}"


def table_rows(rows: Iterable[Tuple[str, Any]]) -> str:
    rendered: List[str] = []
    for key, value in rows:
        rendered.append(
            "".join(
                [
                    "<tr>",
                    f'<td class="label-cell">{html_escape(key)}</td>',
                    f"<td>{html_escape(value)}</td>",
                    "</tr>",
                ]
            )
        )
    return "\n".join(rendered)


def build_subject(prefix: str, alert: Dict[str, Any], level: int) -> str:
    agent_name = as_string(get_path(alert, "agent.name", "unknown-agent"))
    location = as_string(get_path(alert, "location", "unknown-location"))
    return f"{prefix} - ({agent_name}) {location} - Alert level {level}"


def build_context(alert: Dict[str, Any], subject: str) -> Dict[str, str]:
    level = parse_level(get_path(alert, "rule.level", 0))
    palette = severity_palette(level)

    timestamp = format_timestamp_display(
        get_path(alert, "timestamp", get_path(alert, "data.win.system.systemTime", "-"))
    )
    rule_description = as_string(get_path(alert, "rule.description", "No description provided"))
    rule_id = as_string(get_path(alert, "rule.id", "-"))
    agent_name = as_string(get_path(alert, "agent.name", "-"))
    agent_ip = as_string(get_path(alert, "agent.ip", "-"))
    manager_name = as_string(get_path(alert, "manager.name", "-"))
    location = as_string(get_path(alert, "location", "-"))

    summary_rows = [
        ("Subject", subject),
        ("Timestamp", timestamp),
        ("Agent", agent_name),
        ("Agent IP", agent_ip),
        ("Manager", manager_name),
        ("Location", location),
        ("Rule ID", rule_id),
        ("Rule Groups", as_string(get_path(alert, "rule.groups", "-"))),
        ("MITRE ID", as_string(get_path(alert, "rule.mitre.id", "-"))),
        ("MITRE Tactic", as_string(get_path(alert, "rule.mitre.tactic", "-"))),
        ("MITRE Technique", as_string(get_path(alert, "rule.mitre.technique", "-"))),
    ]

    system_rows = [
        ("Provider", get_path(alert, "data.win.system.providerName", "-")),
        ("Provider GUID", get_path(alert, "data.win.system.providerGuid", "-")),
        ("Event ID", get_path(alert, "data.win.system.eventID", "-")),
        ("Channel", get_path(alert, "data.win.system.channel", "-")),
        ("Computer", get_path(alert, "data.win.system.computer", "-")),
        ("Severity Value", get_path(alert, "data.win.system.severityValue", "-")),
        ("System Time", format_timestamp_display(get_path(alert, "data.win.system.systemTime", "-"))),
        ("Record ID", get_path(alert, "data.win.system.eventRecordID", "-")),
        ("Process ID", get_path(alert, "data.win.system.processID", "-")),
        ("Thread ID", get_path(alert, "data.win.system.threadID", "-")),
        ("Task", get_path(alert, "data.win.system.task", "-")),
        ("Opcode", get_path(alert, "data.win.system.opcode", "-")),
        ("Keywords", get_path(alert, "data.win.system.keywords", "-")),
    ]

    event_data = get_path(alert, "data.win.eventdata", {})
    flattened_event_data = flatten_dict(event_data)
    if not flattened_event_data:
        flattened_event_data = [("eventdata", "-")]
    if len(flattened_event_data) > 35:
        flattened_event_data = flattened_event_data[:35] + [("...", "Additional fields omitted")]

    raw_message = normalize_message(as_string(get_path(alert, "data.win.system.message", "-")))
    raw_json = truncate_text(json.dumps(alert, ensure_ascii=False, indent=2), limit=4200)

    return {
        "SUBJECT": html_escape(subject),
        "TIMESTAMP": html_escape(timestamp),
        "AGENT_NAME": html_escape(agent_name),
        "LOCATION": html_escape(location),
        "LEVEL": html_escape(level),
        "SEVERITY_LABEL": html_escape(palette["label"]),
        "LEVEL_BADGE_BG": palette["bg"],
        "LEVEL_BADGE_TEXT": palette["text"],
        "RULE_DESCRIPTION": html_escape(rule_description),
        "RULE_ID": html_escape(rule_id),
        "SUMMARY_ROWS": table_rows(summary_rows),
        "SYSTEM_ROWS": table_rows(system_rows),
        "EVENT_ROWS": table_rows(flattened_event_data),
        "RAW_MESSAGE": html.escape(truncate_text(raw_message, 2400)),
        "RAW_JSON": html.escape(raw_json),
    }


def render_template(template_text: str, context: Dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return context.get(key, "")

    return PLACEHOLDER_RE.sub(replace, template_text)


def build_plain_text(alert: Dict[str, Any], subject: str, level: int) -> str:
    description = as_string(get_path(alert, "rule.description", "No description provided"))
    lines: List[str] = [
        "Wazuh Security Alert",
        "",
        f"Subject: {subject}",
        f"Level: {level}",
        f"Description: {description}",
        f"Timestamp: {format_timestamp_display(get_path(alert, 'timestamp', '-'))}",
        f"Agent: {as_string(get_path(alert, 'agent.name', '-'))}",
        f"Agent IP: {as_string(get_path(alert, 'agent.ip', '-'))}",
        f"Location: {as_string(get_path(alert, 'location', '-'))}",
        f"Rule ID: {as_string(get_path(alert, 'rule.id', '-'))}",
        "",
        "Top Event Fields:",
    ]

    top_event_fields = flatten_dict(get_path(alert, "data.win.eventdata", {}))[:12]
    for key, value in top_event_fields:
        lines.append(f"- {key}: {value}")

    lines.extend(["", "Raw JSON (truncated):", truncate_text(json.dumps(alert, ensure_ascii=False), 1200)])
    return "\n".join(lines)


def send_via_sendmail(sendmail_path: str, message_bytes: bytes) -> None:
    subprocess.run([sendmail_path, "-t", "-i"], input=message_bytes, check=True)


def main() -> int:
    args = parse_args()

    if not args.to_addr:
        print("Missing recipient: use --to or WAZUH_MAIL_TO env var.", file=sys.stderr)
        return 2

    try:
        raw_data = read_input(args.input)
        alert = load_alert_json(raw_data)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Failed to read alert input: {exc}", file=sys.stderr)
        return 1

    level = parse_level(get_path(alert, "rule.level", 0))
    subject = build_subject(args.subject_prefix, alert, level)

    template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
    context = build_context(alert, subject)
    html_body = render_template(template_text, context)
    text_body = build_plain_text(alert, subject, level)

    msg = EmailMessage()
    msg["From"] = args.from_addr
    msg["To"] = args.to_addr
    msg["Subject"] = subject
    msg["Date"] = datetime.now().astimezone().strftime("%a, %d %b %Y %H:%M:%S %z")
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    message_bytes = msg.as_bytes()

    if args.output_html:
        Path(args.output_html).write_text(html_body, encoding="utf-8")
    if args.output_text:
        Path(args.output_text).write_text(text_body, encoding="utf-8")
    if args.output_eml:
        Path(args.output_eml).write_bytes(message_bytes)

    if args.no_send:
        print("Rendered alert e-mail (no-send mode).", file=sys.stderr)
        return 0

    try:
        send_via_sendmail(args.sendmail, message_bytes)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Failed to send e-mail: {exc}", file=sys.stderr)
        return 1

    print(f"Alert sent via {args.sendmail} to {args.to_addr}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
