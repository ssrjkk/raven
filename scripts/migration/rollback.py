#!/usr/bin/env python3
"""Migration rollback script — switches all feature flags to monolith.

Usage:
    python scripts/migration/rollback.py                    # rollback all services
    python scripts/migration/rollback.py --service auth     # rollback specific service
    python scripts/migration/rollback.py --check            # dry-run: only check current state
"""

import argparse
import os

SERVICES = {
    "auth": {"env": "FF_use_auth_service", "desc": "Auth service"},
    "monitor": {"env": "FF_use_monitor_service", "desc": "Monitor engine"},
    "rag": {"env": "FF_use_rag_service", "desc": "RAG service"},
    "code": {"env": "FF_use_code_service", "desc": "Code service"},
    "task": {"env": "FF_use_task_service", "desc": "Task engine"},
    "agent": {"env": "FF_use_agent_service", "desc": "Agent core"},
    "channels": {"env": "FF_use_channels_service", "desc": "Channels service"},
}

SHADOW_FLAGS = {
    "shadow_auth": "FF_shadow_auth",
    "shadow_monitor": "FF_shadow_monitor",
    "shadow_rag": "FF_shadow_rag",
    "shadow_code": "FF_shadow_code",
    "shadow_task": "FF_shadow_task",
    "shadow_agent": "FF_shadow_agent",
}


def current_state():
    print("=" * 60)
    print("Current feature flag state:")
    print("=" * 60)
    all_flags = {**{s["env"]: s["desc"] for s in SERVICES.values()}, **SHADOW_FLAGS}
    for env, desc in all_flags.items():
        val = os.environ.get(env, "not set")
        status = "✅ ACTIVE" if val.lower() == "true" else "⏹️  INACTIVE"
        print(f"  {env:<40} {status}  ({desc})")


def rollback(service: str | None, check: bool = False):
    if check:
        current_state()
        return

    if service:
        targets = [s for s in SERVICES.values() if service in s["env"]]
    else:
        targets = list(SERVICES.values())

    print(f"Rolling back {len(targets)} service(s) to monolith...")
    for svc in targets:
        print(f"  Setting {svc['env']}=false  ({svc['desc']})")
        os.environ[svc["env"]] = "false"

    # Also disable all shadow flags
    for flag, env in SHADOW_FLAGS.items():
        print(f"  Setting {env}=false")
        os.environ[env] = "false"

    print("\n✅ Rollback complete. All traffic now routes through monolith.")
    print("Run `docker compose -f docker-compose.micro.yml restart gateway` to apply.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Strangler Fig rollback script")
    parser.add_argument("--service", "-s", help="Rollback specific service only")
    parser.add_argument("--check", "-c", action="store_true", help="Check current state without rolling back")
    args = parser.parse_args()

    rollback(args.service, check=args.check)
