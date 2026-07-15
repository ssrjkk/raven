"""
Script to verify migration v5 indexes exist and are used in query plans.
100% local, no external dependencies beyond aiosqlite + stdlib.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


# Core DB indexes (migration v5) + store-specific indexes
EXPECTED_INDEXES = {
    "idx_sessions_channel": "sessions",
    "idx_messages_session_id": "messages",
    "idx_messages_created_at": "messages",
    "idx_users_channel": "users",
    "idx_users_external_id": "users",
}


async def main() -> None:
    db_path = Path("data/raven.db").resolve()
    if not db_path.exists():
        print(f"{Colors.YELLOW}Database not found: {db_path}. Run migrations first.{Colors.RESET}")
        return

    print(f"\n{Colors.BOLD}--- Index verification: {db_path} ---{Colors.RESET}\n")

    async with aiosqlite.connect(str(db_path)) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name LIKE 'idx_%'"
        )
        existing = {row[0] for row in await cursor.fetchall()}

    all_present = True
    for idx_name, table in sorted(EXPECTED_INDEXES.items()):
        if idx_name in existing:
            print(f"  {Colors.GREEN}PASS{Colors.RESET}  {idx_name}  ({table})")
        else:
            print(f"  {Colors.RED}FAIL{Colors.RESET}  {idx_name}  ({table})  -- MISSING")
            all_present = False

    # Query plan verification
    print(f"\n{Colors.BOLD}--- Query plan verification ---{Colors.RESET}\n")
    test_queries = [
        ("SELECT 1 FROM messages WHERE session_id = 'test' LIMIT 1", "idx_messages_session_id"),
        ("SELECT 1 FROM messages WHERE created_at > '2020-01-01' LIMIT 1", "idx_messages_created_at"),
        ("SELECT 1 FROM sessions WHERE channel = 'test' LIMIT 1", "idx_sessions_channel"),
        ("SELECT 1 FROM users WHERE channel = 'test' LIMIT 1", "idx_users_channel"),
        ("SELECT 1 FROM users WHERE external_id = 'test' LIMIT 1", "idx_users_external_id"),
    ]
    plans_ok = True
    async with aiosqlite.connect(str(db_path)) as conn:
        for query, target_idx in test_queries:
            cursor = await conn.execute(f"EXPLAIN QUERY PLAN {query}")
            plan = await cursor.fetchall()
            plan_str = " ".join(str(r) for r in plan)
            if "SCAN" in plan_str.upper() and target_idx.upper() not in plan_str.upper():
                print(f"  {Colors.RED}FAIL{Colors.RESET}  {target_idx} -- not used by planner: {plan_str[:120]}")
                plans_ok = False
            else:
                print(f"  {Colors.GREEN}PASS{Colors.RESET}  {target_idx} -- {plan_str[:100]}")

    print(f"\n{Colors.BOLD}--- Summary ---{Colors.RESET}")
    if all_present and plans_ok:
        print(f"  {Colors.GREEN}All indices present and query plans correct.{Colors.RESET}")
    elif all_present:
        print(f"  {Colors.YELLOW}All indices present but some query plans need review.{Colors.RESET}")
    else:
        print(f"  {Colors.RED}Missing indices detected. Re-run migration v5.{Colors.RESET}")


if __name__ == "__main__":
    asyncio.run(main())
