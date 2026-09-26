"""Offline JSONL audit CLI. No network, model calls, or trace upload."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, TextIO
from xml.etree import ElementTree as ET

from .core import TraceFormatError, audit


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def read_events(stream: TextIO) -> Iterable[dict[str, Any]]:
    for line_number, line in enumerate(stream, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line, object_pairs_hook=_object, parse_constant=_invalid_constant)
        except (ValueError, RecursionError) as exc:
            raise TraceFormatError(f"line {line_number}: {exc}") from exc
        if not isinstance(event, dict):
            raise TraceFormatError(f"line {line_number}: expected a JSON object")
        yield event


def _exit_code(results: list[dict[str, Any]], strict: bool) -> int:
    if any("error" in item or item["report"]["status"] == "inconclusive" for item in results):
        return 2
    for item in results:
        report = item["report"]
        if report["status"] == "fail":
            return 1
        if strict and any(f["severity"] == "warning" for f in report["findings"]):
            return 1
    return 0


def _xml_text(value: object) -> str:
    # XML 1.0 excludes some characters that are legal in JSON strings.
    return "".join(c if c in "\t\n\r" or 0x20 <= ord(c) <= 0xD7FF or
                   0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF
                   else "\ufffd" for c in str(value))


def write_junit(results: list[dict[str, Any]], path: Path, strict: bool) -> None:
    suite = ET.Element("testsuite", name="interaction-contracts", tests=str(len(results)))
    failures = errors = skipped = 0
    for item in results:
        case = ET.SubElement(suite, "testcase", name=_xml_text(item["source"]),
                             classname="interaction_contracts.trace")
        if "error" in item:
            errors += 1
            ET.SubElement(case, "error", message="Invalid trace").text = _xml_text(item["error"])
            continue
        report = item["report"]
        failing = [f for f in report["findings"] if f["severity"] == "error" or
                   (strict and f["severity"] == "warning")]
        detail = "\n".join(f"{f['code']} (event {f['event_index']}): {f['message']}" for f in failing)
        if failing:
            failures += 1
            ET.SubElement(case, "failure", message="Interaction contract violated").text = _xml_text(detail)
        elif report["status"] == "inconclusive":
            skipped += 1
            ET.SubElement(case, "skipped", message="No accepted resume was observed")
        ET.SubElement(case, "system-out").text = _xml_text(json.dumps(report, ensure_ascii=True))
    suite.set("failures", str(failures))
    suite.set("errors", str(errors))
    suite.set("skipped", str(skipped))
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check human-reply routing in ordered JSONL traces.")
    parser.add_argument("traces", nargs="+", help="Trace files, or - for standard input; each is audited separately")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as CI failures")
    parser.add_argument("--junit", type=Path, help="Write JUnit XML for CI")
    parser.add_argument("--version", action="version", version="interaction-contracts 0.1.0a1")
    args = parser.parse_args(argv)
    if args.traces.count("-") > 1:
        parser.error("standard input can only be read once")
    if args.junit and any(source != "-" and Path(source).resolve() == args.junit.resolve()
                          for source in args.traces):
        parser.error("JUnit output must not overwrite an input trace")
    results: list[dict[str, Any]] = []
    for source in args.traces:
        try:
            if source == "-":
                report = audit(read_events(sys.stdin))
            else:
                with Path(source).open(encoding="utf-8") as stream:
                    report = audit(read_events(stream))
            results.append({"source": source, "report": report.to_dict()})
        except (OSError, UnicodeError, TraceFormatError) as exc:
            results.append({"source": source, "error": str(exc)})
    if args.format == "json":
        print(json.dumps({"schema_version": "1", "results": results}, indent=2, ensure_ascii=True))
    else:
        for item in results:
            if "error" in item:
                print(f"INVALID {item['source']}: {item['error']}")
                continue
            report = item["report"]
            print(f"{report['status'].upper()} {item['source']}")
            for finding in report["findings"]:
                index = finding["event_index"]
                where = f"event {index}" if index is not None else "end of trace"
                print(f"  {finding['severity']} {finding['code']} [{where}]: {finding['message']}")
    if args.junit:
        try:
            write_junit(results, args.junit, args.strict)
        except OSError as exc:
            print(f"Unable to write JUnit report: {exc}", file=sys.stderr)
            return 2
    return _exit_code(results, args.strict)
