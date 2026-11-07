"""Explicit JSON CLI for engineering context and its reproducible validation."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from minimax_sdd.minimax_client import develop, write_json
from minimax_sdd.state import TaskState
from minimax_sdd.workflow import context_for_run, prepare, reset, verify, versions


async def dispatch(arguments):
    if arguments.command == "versions":
        return versions()
    if arguments.command == "prepare":
        return await prepare(arguments.project, arguments.run_dir, arguments.project_id)
    if arguments.command == "context":
        result = await context_for_run(arguments.run_dir)
        if arguments.output:
            write_json(arguments.output, result)
        return result
    if arguments.command == "develop":
        context = json.loads(arguments.context.read_text(encoding="utf-8"))
        record = await develop(context, arguments.record)
        return {
            "provider": record["provider"],
            "model": record["response_model"],
            "response_id": record["response_id"],
            "record": str(arguments.record),
        }
    if arguments.command == "verify":
        return await verify(arguments.run_dir, json.loads(arguments.record.read_text(encoding="utf-8")))
    if arguments.command == "state-show":
        return await TaskState(arguments.state_dir, arguments.project_id).load(arguments.task_id)
    if arguments.command == "reset":
        return reset(arguments.run_dir)
    raise ValueError("unknown command")


def main():
    parser = argparse.ArgumentParser(description="MiniMax + seekdb + PowerContext SDD context module")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("versions")
    prepared = commands.add_parser("prepare")
    prepared.add_argument("--project", type=Path, required=True)
    prepared.add_argument("--run-dir", type=Path, required=True)
    prepared.add_argument("--project-id", default="orders-demo")
    context = commands.add_parser("context")
    context.add_argument("--run-dir", type=Path, required=True)
    context.add_argument("--output", type=Path)
    developer = commands.add_parser("develop")
    developer.add_argument("--context", type=Path, required=True)
    developer.add_argument("--record", type=Path, required=True)
    verified = commands.add_parser("verify")
    verified.add_argument("--run-dir", type=Path, required=True)
    verified.add_argument("--record", type=Path, required=True)
    state = commands.add_parser("state-show")
    state.add_argument("--state-dir", type=Path, required=True)
    state.add_argument("--project-id", default="orders-demo")
    state.add_argument("--task-id", required=True)
    clean = commands.add_parser("reset")
    clean.add_argument("--run-dir", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = asyncio.run(dispatch(arguments))
    except (ValueError, OSError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from None
    print(json.dumps(result, ensure_ascii=False, indent=2))
