#!/usr/bin/env python3
"""
Post a HumanQ task to Roam Research.

Takes JSON as first argument (or stdin) describing the task.
Handles UID generation, block creation, and tracking.

Input format:
{
  "title": "Short task description",
  "project": "project-name",
  "why": "Context about what you're doing",
  "provide_back": "What info you need returned",
  "notes": "Caveats, timing, gotchas",
  "steps": [
    {"text": "Step 1: Do something", "details": ["detail 1", "detail 2"]},
    {"text": "Step 2: Do another thing"}
  ]
}
"""

import json
import os
import sys
import time
import subprocess
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROAM_SH = os.path.join(SCRIPT_DIR, "roam.sh")
CONFIG_DIR = os.path.expanduser("~/.config/pluginterface/humanq")
TASKS_FILE = os.path.expanduser("~/.config/pluginterface/humanq/tasks.json")


def get_config(name):
    path = os.path.join(CONFIG_DIR, name)
    if not os.path.exists(path):
        print(f"Error: HumanQ not configured (missing {name}). Run /humanq:setup first.", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return f.read().strip()


def new_uid():
    return f"hq_{int(time.time())}_{os.urandom(4).hex()}"


def roam_write(body):
    result = subprocess.run(
        [ROAM_SH, "write", json.dumps(body)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def create_block(parent_uid, text, uid=None):
    uid = uid or new_uid()
    roam_write({
        "action": "create-block",
        "location": {"parent-uid": parent_uid, "order": "last"},
        "block": {"string": text, "uid": uid}
    })
    return uid


def ordinal(n):
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{['th','st','nd','rd','th'][min(n%10,4)]}"


def roam_date():
    now = datetime.now()
    day = ordinal(now.day)
    return now.strftime(f"%B {day}, %Y")


def main():
    if len(sys.argv) > 1:
        task = json.loads(sys.argv[1])
    else:
        task = json.load(sys.stdin)

    page_uid = get_config("page_uid")

    title = task["title"]
    project = task.get("project", os.path.basename(os.getcwd()))
    date_str = roam_date()

    # Parent TODO
    parent_uid = new_uid()
    parent_text = f"{{{{[[TODO]]}}}} {title} — [[{project}]] — [[{date_str}]]"
    create_block(page_uid, parent_text, parent_uid)

    # Why
    if task.get("why"):
        create_block(parent_uid, f"**Why:** {task['why']}")

    # Steps (as nested TODOs)
    for step in task.get("steps", []):
        step_uid = create_block(parent_uid, f"{{{{[[TODO]]}}}} {step['text']}")
        for detail in step.get("details", []):
            create_block(step_uid, detail)

    # Provide back
    if task.get("provide_back"):
        create_block(parent_uid, f"**Provide back:** {task['provide_back']}")

    # Notes
    if task.get("notes"):
        create_block(parent_uid, f"**Notes:** {task['notes']}")

    # Track locally
    if not os.path.exists(TASKS_FILE):
        os.makedirs(os.path.dirname(TASKS_FILE), exist_ok=True)
        with open(TASKS_FILE, "w") as f:
            json.dump([], f)

    with open(TASKS_FILE) as f:
        tasks = json.load(f)

    tasks.append({
        "uid": parent_uid,
        "description": title,
        "project": project,
        "created": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "pending"
    })

    with open(TASKS_FILE, "w") as f:
        json.dump(tasks, f, indent=2)

    print(json.dumps({"uid": parent_uid, "status": "posted"}))


if __name__ == "__main__":
    main()
