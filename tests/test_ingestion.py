"""Ingestion tests use small in-memory samples, so they run without the downloaded data."""
import json

from app.ingestion.logs import load_log_file
from app.ingestion.postmortems import load_postmortems
from app.ingestion.runbooks import parse_runbook
from app.ingestion.text import normalize_text
from app.ingestion.tickets import load_tickets

RUNBOOK = """---
title: Kube Pod Crash Looping
weight: 20
---

# KubePodCrashLooping

## Meaning

Pod is in CrashLoop which means the app dies or is unresponsive.

## Mitigation

Fix the app configuration.
"""

POSTMORTEMS = """# A List of Post-mortems!

## Table of Contents
[Config Errors](#config-errors)

## Config Errors

[Acme](https://acme.example/postmortem). A bad config push removed the DNS minimum healthy hosts setting and queries failed for an hour.
[Tiny](https://tiny.example). Too short.

## Contributors
[Someone](https://github.com/someone). Thanks for all the contributions to this list over the years!
"""

LOG_CSV = """LineId,Date,Time,Level,Component,Content,EventId,EventTemplate
1,081109,203615,INFO,dfs.DataNode,Receiving block blk_1,E1,Receiving block <*>
2,081109,203616,INFO,dfs.DataNode,Receiving block blk_2,E1,Receiving block <*>
3,081109,203617,WARN,dfs.DataNode,Exception writing block blk_3,E2,Exception writing block <*>
"""


def test_parse_runbook(tmp_path):
    p = tmp_path / "kubernetes__KubePodCrashLooping.md"
    p.write_text(RUNBOOK, encoding="utf-8")
    doc = parse_runbook(p)
    assert doc.source_type == "runbook"
    assert doc.metadata == {"component": "kubernetes", "alert": "KubePodCrashLooping",
                            "sections": ["Meaning", "Mitigation"]}
    assert "weight: 20" not in doc.text  # front matter removed
    assert doc.source.endswith("/kubernetes/kubepodcrashlooping/")


def test_runbook_ids_are_stable(tmp_path):
    p = tmp_path / "kubernetes__KubePodCrashLooping.md"
    p.write_text(RUNBOOK, encoding="utf-8")
    assert parse_runbook(p).id == parse_runbook(p).id


def test_postmortems_skip_short_entries_and_non_incident_sections(tmp_path):
    p = tmp_path / "README.md"
    p.write_text(POSTMORTEMS, encoding="utf-8")
    docs = load_postmortems(p)
    assert [d.metadata["company"] for d in docs] == ["Acme"]
    assert docs[0].metadata["category"] == "Config Errors"
    assert docs[0].source == "https://acme.example/postmortem"


def test_logs_grouped_by_template(tmp_path):
    p = tmp_path / "HDFS.csv"
    p.write_text(LOG_CSV, encoding="utf-8")
    docs = {d.metadata["event_id"]: d for d in load_log_file(p)}
    assert set(docs) == {"E1", "E2"}
    assert docs["E1"].metadata["count"] == 2
    assert docs["E2"].metadata["levels"] == {"WARN": 1}
    assert "Receiving block blk_1" in docs["E1"].text


def test_tickets(tmp_path):
    p = tmp_path / "tickets.jsonl"
    ticket = {"ticket_id": "INC-0001", "title": "Pods restarting", "description": "CrashLoopBackOff",
              "root_cause": "OOM", "resolution": "Raised memory limit", "priority": "P1",
              "service": "checkout-api", "related_runbook": "KubePodCrashLooping"}
    p.write_text(json.dumps(ticket) + "\n", encoding="utf-8")
    [doc] = load_tickets(p)
    assert doc.metadata["related_runbook"] == "KubePodCrashLooping"
    assert "Root cause: OOM" in doc.text


def test_missing_ticket_file_is_ok(tmp_path):
    assert load_tickets(tmp_path / "nope.jsonl") == []


def test_normalize_text():
    assert normalize_text("reporting‑etl “down” now") == 'reporting-etl "down" now'
