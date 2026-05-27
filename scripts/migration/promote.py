#!/usr/bin/env python3
"""Promote a service: disable monolith path, enable microservice.

Usage:
    python scripts/migration/promote.py --service auth
    python scripts/migration/promote.py --all
"""

import argparse
import os

SERVICES = [
    {"name": "channels",   "flag": "FF_use_channels_service",  "shadow": "FF_shadow_channels"},
    {"name": "monitor",    "flag": "FF_use_monitor_service",   "shadow": "FF_shadow_monitor"},
    {"name": "rag",        "flag": "FF_use_rag_service",       "shadow": "FF_shadow_rag"},
    {"name": "code",       "flag": "FF_use_code_service",      "shadow": "FF_shadow_code"},
    {"name": "task",       "flag": "FF_use_task_service",      "shadow": "FF_shadow_task"},
    {"name": "agent",      "flag": "FF_use_agent_service",     "shadow": "FF_shadow_agent"},
    {"name": "auth",       "flag": "FF_use_auth_service",      "shadow": "FF_shadow_auth"},
]


def promote(service_name: str | None, shadow_first: bool = True):
    targets = SERVICES if service_name is None or service_name == "all" else [s for s in SERVICES if s["name"] == service_name]

    if not targets:
        print(f"Unknown service: {service_name}")
        return

    for svc in targets:
        if shadow_first:
            print(f"[{svc['name']}] Enabling SHADOW mode first ({svc['shadow']}=true)")
            os.environ[svc["shadow"]] = "true"
            print(f"[{svc['name']}] Monitor metrics for drift. Run promote again to switch to microservice.")

        print(f"[{svc['name']}] DISABLING shadow ({svc['shadow']}=false)")
        print(f"[{svc['name']}] ENABLING microservice ({svc['flag']}=true)")
        os.environ[svc["shadow"]] = "false"
        os.environ[svc["flag"]] = "true"
        print(f"[{svc['name']}] ✅ Promoted to microservice")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Promote service to microservice")
    parser.add_argument("--service", "-s", default="all", help="Service name to promote")
    parser.add_argument("--shadow-only", action="store_true", help="Only enable shadow, don't switch traffic")
    args = parser.parse_args()

    promote(args.service, shadow_first=args.shadow_only)
