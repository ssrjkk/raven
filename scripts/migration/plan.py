#!/usr/bin/env python3
"""
Migration plan: Raven Monolith → Microservices
===============================================

Order: channels → monitor-engine → rag-service → code-service → task-engine → auth → agent-core

Each step:
  1. Deploy microservice alongside monolith
  2. Enable shadow traffic (dual-write, compare results)
  3. Validate metrics parity (latency, error rate <5% delta)
  4. Enable feature flag (route traffic to microservice)
  5. Monitor for 24h
  6. Decommission monolith path

Run:
  python scripts/migration/promote.py --shadow-only --service <name>   # step 2
  python scripts/migration/promote.py --service <name>                 # step 4

Rollback:
  python scripts/migration/rollback.py --service <name>                # revert to monolith
"""

import subprocess
import sys
import time

STEPS = [
    {"name": "channels", "desc": "Channels adapters (Telegram, Discord, Matrix)", "risk": "Low"},
    {"name": "monitor", "desc": "Monitor engine (stateless workers)", "risk": "Low"},
    {"name": "rag", "desc": "RAG service (vector DB isolation)", "risk": "Medium"},
    {"name": "code", "desc": "Code service (sandboxed execution)", "risk": "Medium"},
    {"name": "task", "desc": "Task engine (tool policy boundary)", "risk": "Medium"},
    {"name": "auth", "desc": "Auth service (JWT, RBAC isolation)", "risk": "High"},
    {"name": "agent", "desc": "Agent core (LLM routing, state management)", "risk": "High"},
]


def run_step(step: dict[str, str], dry_run: bool = False) -> None:
    print(f"\n{'=' * 60}")
    print(f"Step: {step['name']} — {step['desc']}")
    print(f"Risk: {step['risk']}")
    print(f"{'=' * 60}")

    if dry_run:
        print(f"  [DRY-RUN] python scripts/migration/promote.py --shadow-only --service {step['name']}")
        print("  [DRY-RUN] <monitor for 24h>")
        print(f"  [DRY-RUN] python scripts/migration/promote.py --service {step['name']}")
        print(f"  [DRY-RUN] python scripts/migration/rollback.py --service {step['name']}  (if needed)")
        return

    confirm = input(f"  Ready to promote {step['name']}? [y/N] ")
    if confirm.lower() != "y":
        print("  Skipped.")
        return

    print("  Enabling shadow mode...")
    subprocess.run([sys.executable, "scripts/migration/promote.py", "--shadow-only", "--service", step["name"]])  # noqa: S603 — sys.executable trusted
    print(f"  ✅ Shadow mode active for {step['name']}")
    print(f"  Monitor for drift. Run '--service {step['name']}' again to switch traffic.")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv

    print("Raven Migration Plan — Strangler Fig")
    print(f"{'Step':<15} {'Risk':<10} {'Description'}")
    print("-" * 60)
    for i, step in enumerate(STEPS, 1):
        print(f"{i}. {step['name']:<10} {step['risk']:<10} {step['desc']}")
    print()

    if not dry:
        for step in STEPS:
            run_step(step, dry_run=False)
            time.sleep(1)  # noqa: ASYNC100 — sync migration script
    else:
        for step in STEPS:
            run_step(step, dry_run=True)
