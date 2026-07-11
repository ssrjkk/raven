#!/usr/bin/env python3
"""CLI tool for managing NATS JetStream streams and consumers.

Usage:
    python deploy/nats/nats-stream-manager.py list-streams
    python deploy/nats/nats-stream-manager.py list-consumers <stream>
    python deploy/nats/nats-stream-manager.py create-stream <name> --subjects "a.b.c,x.y.z" --max-age 72h
    python deploy/nats/nats-stream-manager.py delete-stream <name>
    python deploy/nats/nats-stream-manager.py purge-stream <name>
    python deploy/nats/nats-stream-manager.py add-consumer <stream> <name> --filter "events.>"
    python deploy/nats/nats-stream-manager.py verify
    python deploy/nats/nats-stream-manager.py validate <nats.conf>
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

try:
    import nats
    from nats.js.api import ConsumerConfig, StreamConfig
except ImportError:
    print("nats-py not installed. Run: pip install nats-py")
    sys.exit(1)

NATS_URL = "nats://localhost:4222"
CONF_PATH = Path(__file__).parent / "nats.conf"


async def get_js():
    nc = await nats.connect(NATS_URL)
    js = nc.jetstream()
    return nc, js


async def list_streams():
    nc, js = await get_js()
    try:
        streams = await js.streams_info()
        if not streams:
            print("No streams configured.")
            return
        print(f"{'NAME':<30} {'MESSAGES':<10} {'BYTES':<15} {'SUBJECTS'}")
        print("-" * 80)
        for s in streams:
            subjects = ", ".join(s.config.subjects) if s.config.subjects else "-"
            print(f"{s.config.name:<30} {s.state.messages:<10} {s.state.bytes:<15} {subjects}")
    finally:
        await nc.close()


async def list_consumers(stream: str):
    nc, js = await get_js()
    try:
        consumers = await js.consumers_info(stream)
        if not consumers:
            print(f"No consumers for stream '{stream}'.")
            return
        print(f"{'NAME':<25} {'ACK_PENDING':<15} {'DELIVERED':<12} {'FILTER'}")
        print("-" * 70)
        for c in consumers:
            filt = c.config.filter_subject or "-"
            print(f"{c.name:<25} {c.num_ack_pending:<15} {c.num_delivered:<12} {filt}")
    finally:
        await nc.close()


async def create_stream(name: str, subjects: list[str], max_age: float = 604800.0):
    nc, js = await get_js()
    try:
        cfg = StreamConfig(name=name, subjects=subjects, max_age=max_age)
        await js.add_stream(cfg)
        print(f"Stream '{name}' created (subjects={subjects}, max_age={max_age})")
    except Exception as e:
        print(f"Error creating stream: {e}")
    finally:
        await nc.close()


async def delete_stream(name: str):
    nc, js = await get_js()
    try:
        await js.delete_stream(name)
        print(f"Stream '{name}' deleted.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await nc.close()


async def purge_stream(name: str):
    nc, js = await get_js()
    try:
        await js.purge_stream(name)
        print(f"Stream '{name}' purged.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await nc.close()


async def add_consumer(stream: str, name: str, filter_subject: str = ""):
    nc, js = await get_js()
    try:
        cfg = ConsumerConfig(
            name=name,
            durable_name=name,
            deliver_subject="",
            filter_subject=filter_subject or None,
            ack_policy=nats.js.api.AckPolicy.EXPLICIT,
            max_deliver=5,
            ack_wait=30,
        )
        await js.add_consumer(stream, cfg)
        print(f"Consumer '{name}' added to stream '{stream}' (filter={filter_subject or 'none'})")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await nc.close()


async def verify():
    nc, js = await get_js()
    try:
        streams = await js.streams_info()
        names = {s.config.name for s in streams}
        print(f"Connected to {NATS_URL}")
        print(f"Streams ({len(streams)}): {', '.join(sorted(names))}")
        for s in streams:
            c = await js.consumers_info(s.config.name)
            print(f"  {s.config.name}: {s.state.messages} msgs, {len(c)} consumers")
            for cons in c:
                print(f"    └ {cons.name}: {cons.num_pending} pending, {cons.num_ack_pending} ack_pending")
        print("✅ OK")
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await nc.close()


def validate_file(path: str):
    """Validate nats.conf syntax (basic)."""
    content = Path(path).read_text()
    errors = []
    for i, line in enumerate(content.splitlines(), 1):
        stripped = line.strip()
        if (
            stripped
            and not stripped.startswith("#")
            and "=" not in stripped
            and not stripped.endswith("{")
            and not stripped.endswith("}")
            and not any(kw in stripped for kw in ["include", "listen", "port", "host"])
            and re.match(r"^\s*\w[\w_]*\s*:", stripped)
        ):
            continue
        errors.append(f"Line {i}: possible syntax issue — {stripped[:60]}")
    if errors:
        print(f"⚠️  Found {len(errors)} potential issues in {path}:")
        for e in errors:
            print(f"  {e}")
    else:
        print(f"✅ {path}: no obvious syntax issues")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NATS JetStream Manager")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list-streams", help="List all streams")
    list_c = sub.add_parser("list-consumers", help="List consumers for a stream")
    list_c.add_argument("stream")

    create_c = sub.add_parser("create-stream", help="Create a stream")
    create_c.add_argument("name")
    create_c.add_argument("--subjects", required=True, help="Comma-separated subjects")
    create_c.add_argument("--max-age", default="168h")

    del_c = sub.add_parser("delete-stream", help="Delete a stream")
    del_c.add_argument("name")

    purge_c = sub.add_parser("purge-stream", help="Purge all messages from a stream")
    purge_c.add_argument("name")

    add_c = sub.add_parser("add-consumer", help="Add a consumer to a stream")
    add_c.add_argument("stream")
    add_c.add_argument("name")
    add_c.add_argument("--filter", default="")

    sub.add_parser("verify", help="Verify NATS connectivity and state")

    val_c = sub.add_parser("validate", help="Validate nats.conf syntax")
    val_c.add_argument("path", nargs="?", default=str(CONF_PATH))

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "validate":
        validate_file(args.path)
    else:
        asyncio.run(
            globals()[args.command.replace("-", "_")](**{k: v for k, v in vars(args).items() if k != "command"})
        )
