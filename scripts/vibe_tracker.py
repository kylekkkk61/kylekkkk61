# /// script
# requires-python = ">=3.11"
# dependencies = ["tiktoken==0.13.0"]
# ///

import glob
import json
import os
import re
import selectors
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import tiktoken

PROJECT_DIR = Path("/Users/kyle/Projects/kylekkkk61")
README_PATH = PROJECT_DIR / "README.md"
STATE_PATH = PROJECT_DIR / ".vibe_stats.json"
AG_BRAIN_DIR = Path(os.path.expanduser("~/.gemini/antigravity/brain"))
CODEX_SESSIONS_DIR = Path(os.path.expanduser("~/.codex/sessions"))
CODEX_ARCHIVED_DIR = Path(os.path.expanduser("~/.codex/archived_sessions"))
CODEX_DB_PATH = Path(os.path.expanduser("~/.codex/state_5.sqlite"))
LOCAL_TIMEZONE = ZoneInfo("Asia/Taipei")
TOKENIZER = tiktoken.get_encoding("o200k_base")
STATE_VERSION = 1


def parse_day(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(LOCAL_TIMEZONE).date().isoformat()
    except ValueError:
        return None


def count_tokens(text):
    return len(TOKENIZER.encode_ordinary(text)) if text else 0


def empty_day():
    return {"human_prompts": 0, "human_tokens": 0, "agent_tokens": 0}


def add_text(days, day, field, text):
    if not day or not text:
        return
    bucket = days.setdefault(day, empty_day())
    bucket[field] += count_tokens(text)


def get_codex_human_sources():
    if not CODEX_DB_PATH.exists():
        return {}
    with sqlite3.connect(CODEX_DB_PATH) as connection:
        rows = connection.execute("SELECT rollout_path, source FROM threads").fetchall()
    sources = {}
    for path, source in rows:
        is_human = not source.startswith('{"subagent"')
        sources[path] = sources.get(path, False) or is_human
    return sources


def scan_codex(days):
    source_overrides = get_codex_human_sources()
    paths = {Path(path) for path in source_overrides if Path(path).is_file()}
    paths.update(CODEX_SESSIONS_DIR.glob("**/rollout-*.jsonl"))
    paths.update(CODEX_ARCHIVED_DIR.glob("**/rollout-*.jsonl"))

    for path in paths:
        human_allowed = False
        with path.open("r", encoding="utf-8", errors="replace") as transcript:
            for line in transcript:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if event.get("type") == "session_meta":
                    source = (event.get("payload") or {}).get("source")
                    human_allowed = source_overrides.get(
                        str(path),
                        not (isinstance(source, dict) and "subagent" in source),
                    )
                    continue

                if event.get("type") != "event_msg":
                    continue

                payload = event.get("payload") or {}
                event_type = payload.get("type")
                day = parse_day(event.get("timestamp"))
                if event_type == "user_message" and human_allowed:
                    bucket = days.setdefault(day, empty_day()) if day else None
                    if bucket is not None:
                        bucket["human_prompts"] += 1
                    add_text(days, day, "human_tokens", payload.get("message") or "")
                elif event_type == "agent_message":
                    add_text(days, day, "agent_tokens", payload.get("message") or "")


def scan_antigravity(days):
    command_count = 0
    pattern = AG_BRAIN_DIR / "*" / ".system_generated" / "logs" / "transcript.jsonl"

    for path_string in glob.glob(str(pattern)):
        with open(path_string, "r", encoding="utf-8", errors="replace") as transcript:
            for line in transcript:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                created_at = event.get("created_at")
                day = parse_day(created_at)
                if event.get("type") == "USER_INPUT" and event.get("source") == "USER_EXPLICIT":
                    bucket = days.setdefault(day, empty_day()) if day else None
                    if bucket is not None:
                        bucket["human_prompts"] += 1
                    add_text(days, day, "human_tokens", event.get("content") or "")
                    command_count += 1
                elif event.get("source") == "MODEL":
                    add_text(days, day, "agent_tokens", event.get("content") or "")

    return command_count


def scan_workflow_stats():
    days = {}
    scan_codex(days)
    ag_command_count = scan_antigravity(days)
    return days, ag_command_count


def load_state():
    if not STATE_PATH.exists():
        return {"version": STATE_VERSION, "days": {}}
    with STATE_PATH.open("r", encoding="utf-8") as state_file:
        state = json.load(state_file)
    if state.get("version") != STATE_VERSION or not isinstance(state.get("days"), dict):
        raise ValueError("Unsupported vibe stats state")
    return state


def merge_daily_stats(stored_days, scanned_days, today=None):
    merged = {day: dict(values) for day, values in stored_days.items()}
    today = today or datetime.now(LOCAL_TIMEZONE).date()
    mutable_from = (today - timedelta(days=1)).isoformat()
    for day, values in scanned_days.items():
        if day in merged and day < mutable_from:
            continue
        bucket = merged.setdefault(day, empty_day())
        for field in empty_day():
            # ponytail: finalized days are immutable and recent days max-merge;
            # use OTel event IDs if same-day partial purges must be recoverable.
            bucket[field] = max(int(bucket.get(field, 0)), int(values.get(field, 0)))
    return dict(sorted(merged.items()))


def get_codex_productivity_stats():
    if not CODEX_DB_PATH.exists():
        return 0, 0
    try:
        with sqlite3.connect(CODEX_DB_PATH) as connection:
            row = connection.execute("SELECT count(*) FROM threads").fetchone()
        return (row[0] or 0) * 15
    except sqlite3.Error as error:
        raise RuntimeError(f"Unable to read Codex productivity stats: {error}") from error


def read_rpc_response(process, selector, request_id, timeout=20):
    deadline = datetime.now().timestamp() + timeout
    while datetime.now().timestamp() < deadline:
        remaining = max(0, deadline - datetime.now().timestamp())
        for key, _ in selector.select(timeout=min(1, remaining)):
            line = key.fileobj.readline()
            if not line:
                continue
            message = json.loads(line)
            if message.get("id") == request_id:
                return message
    raise TimeoutError(f"Codex app-server request {request_id} timed out")


def _get_codex_account_usage_once():
    process = subprocess.Popen(
        ["codex", "app-server", "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)

    def send(message):
        process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()

    try:
        send(
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "vibe-tracker", "version": "1.0.0"}
                },
            }
        )
        initialized = read_rpc_response(process, selector, 1)
        if "result" not in initialized:
            raise RuntimeError(f"Codex app-server initialization failed: {initialized}")

        send({"method": "initialized", "params": {}})
        send({"id": 2, "method": "account/usage/read", "params": None})
        response = read_rpc_response(process, selector, 2)
        if "result" not in response:
            raise RuntimeError(f"Codex account usage request failed: {response}")

        result = response["result"]
        lifetime_tokens = (result.get("summary") or {}).get("lifetimeTokens")
        if not isinstance(lifetime_tokens, int) or lifetime_tokens <= 0:
            raise RuntimeError("Codex account usage returned no lifetime tokens")
        return result
    finally:
        selector.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def get_codex_account_usage():
    for attempt in range(3):
        try:
            return _get_codex_account_usage_once()
        except (RuntimeError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(10)


def format_number(number):
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.1f}K"
    return str(number)


def generate_sparkline(daily_buckets, days=14, today=None):
    values_by_day = {
        bucket["startDate"]: int(bucket["tokens"])
        for bucket in daily_buckets or []
        if bucket.get("startDate") and bucket.get("tokens") is not None
    }
    today = today or datetime.now(LOCAL_TIMEZONE).date()
    dates = [today - timedelta(days=offset) for offset in range(days, 0, -1)]
    values = [values_by_day.get(day.isoformat(), 0) for day in dates]
    maximum = max(values, default=0)
    if maximum == 0:
        return "▁" * days
    levels = "▁▂▃▄▅▆▇█"
    return "".join(levels[round((value / maximum) * (len(levels) - 1))] for value in values)


def render_stats(account_usage, days, command_count):
    totals = {
        field: sum(int(bucket.get(field, 0)) for bucket in days.values())
        for field in empty_day()
    }
    human_tokens = totals["human_tokens"]
    leverage = totals["agent_tokens"] / human_tokens if human_tokens else 0
    throughput = format_number(account_usage["summary"]["lifetimeTokens"])
    sparkline = generate_sparkline(account_usage.get("dailyUsageBuckets"))

    saved_minutes = command_count * 15
    human_life_saved = f"{saved_minutes // 60} hrs {saved_minutes % 60} mins"

    return f"""```text
⌘ AI-Native Build Workflow

I build through an AI-native workflow: combining coding agents, structured prompts, review loops, and lightweight agent harnesses to turn product ideas into tested, documented, working systems.

Time Reclaimed: {human_life_saved}
Decisions Made: {command_count}

AI Workflow Metrics:
AI Workflow Throughput   {throughput:>7} tokens
Last 14 Days             {sparkline}
Human Prompts            {totals['human_prompts']:>7,}
Output Leverage          1× Direction ──[ AI WORKFLOW ]──▶ {leverage:.1f}× Execution
```"""


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as temporary:
        temporary.write(content)
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, path)


def update_readme(stats_text):
    if not README_PATH.exists():
        raise FileNotFoundError(f"README not found at {README_PATH}")

    content = README_PATH.read_text(encoding="utf-8")
    pattern = r"(<!--START_SECTION:vibe-->).*?(<!--END_SECTION:vibe-->)"
    if re.search(pattern, content, re.DOTALL):
        content = re.sub(
            pattern,
            lambda match: f"{match.group(1)}\n{stats_text}\n{match.group(2)}",
            content,
            flags=re.DOTALL,
        )
    else:
        content += f"\n<!--START_SECTION:vibe-->\n{stats_text}\n<!--END_SECTION:vibe-->\n"
    atomic_write(README_PATH, content)


def main():
    account_usage = get_codex_account_usage()
    scanned_days, ag_command_count = scan_workflow_stats()
    state = load_state()
    merged_days = merge_daily_stats(state["days"], scanned_days)
    codex_command_count = get_codex_productivity_stats()

    output = render_stats(
        account_usage,
        merged_days,
        ag_command_count + codex_command_count,
    )
    update_readme(output)
    atomic_write(
        STATE_PATH,
        json.dumps(
            {"version": STATE_VERSION, "days": merged_days},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    print(output)
    print("README.md and .vibe_stats.json updated successfully")


if __name__ == "__main__":
    main()
