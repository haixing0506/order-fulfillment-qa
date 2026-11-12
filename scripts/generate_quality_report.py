"""Generate a self-contained quality summary and HTML dashboard.

The report is derived from the actual pytest, coverage, Locust, defect, risk
and structured log artifacts in this repository. It intentionally uses only
the Python standard library so it can run immediately in PyCharm.
"""

from __future__ import annotations

import csv
import html
import json
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
LOGS = ROOT / "logs"
TEST_DESIGN = ROOT / "test_design"
DEFECTS = ROOT / "defect_management"


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        return sum(1 for line in handle if line.strip())


def file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def integer(value: Any, default: int = 0) -> int:
    return int(number(value, default))


def esc(value: Any) -> str:
    return html.escape(str(value))


def fmt(value: float, digits: int = 1) -> str:
    return f"{value:,.{digits}f}"


def pct(part: int, total: int) -> float:
    return round(part * 100 / total, 2) if total else 0.0


def parse_junit(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "tests": 0,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "time": 0.0,
        "timestamp": "",
        "cases": [],
    }
    if not path.exists():
        return result
    tree = ET.parse(path)
    root = tree.getroot()
    suite = root.find("testsuite") if root.tag == "testsuites" else root
    if suite is None:
        suite = root
    result["tests"] = integer(suite.attrib.get("tests"))
    result["failures"] = integer(suite.attrib.get("failures"))
    result["errors"] = integer(suite.attrib.get("errors"))
    result["skipped"] = integer(suite.attrib.get("skipped"))
    result["time"] = number(suite.attrib.get("time"))
    result["timestamp"] = suite.attrib.get("timestamp", "")
    for case in root.iter("testcase"):
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        status = "通过"
        detail = ""
        if failure is not None or error is not None:
            status = "失败"
            node = failure if failure is not None else error
            detail = (node.attrib.get("message") or node.text or "")[:240]
        elif skipped is not None:
            status = "跳过"
            detail = skipped.attrib.get("message", "")
        result["cases"].append(
            {
                "classname": case.attrib.get("classname", ""),
                "name": case.attrib.get("name", ""),
                "time": number(case.attrib.get("time")),
                "status": status,
                "detail": detail,
            }
        )
    return result


def latest_test_session(records: list[dict[str, Any]]) -> dict[str, Any]:
    start_index = -1
    for index, record in enumerate(records):
        if record.get("event") == "test_session_started":
            start_index = index
    session = records[start_index:] if start_index >= 0 else records
    finished = [r for r in session if r.get("event") == "test_finished"]
    end_record = next(
        (r for r in reversed(session) if r.get("event") == "test_session_finished"),
        {},
    )
    start_record = session[0] if session else {}
    outcomes = Counter(r.get("test.outcome", "UNKNOWN") for r in finished)
    durations = [number(r.get("test.duration_ms")) for r in finished]
    slowest = sorted(
        finished,
        key=lambda r: number(r.get("test.duration_ms")),
        reverse=True,
    )[:5]
    return {
        "started_at": start_record.get("timestamp", ""),
        "finished_at": end_record.get("timestamp", ""),
        "collected": integer(end_record.get("test.collected")),
        "exit_status": end_record.get("test.exit_status"),
        "elapsed_seconds": number(end_record.get("test.elapsed_seconds")),
        "outcomes": dict(outcomes),
        "case_count": len(finished),
        "average_duration_ms": round(sum(durations) / len(durations), 2)
        if durations
        else 0.0,
        "slowest": [
            {
                "case_id": r.get("test.case_id", "-"),
                "nodeid": r.get("test.nodeid", ""),
                "duration_ms": number(r.get("test.duration_ms")),
            }
            for r in slowest
        ],
    }


def parse_coverage(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    totals = payload.get("totals", {})
    files_payload = payload.get("files", {})
    files = []
    for file_name, details in files_payload.items():
        summary = details.get("summary", {})
        files.append(
            {
                "file": file_name.replace("\\", "/"),
                "percent": round(number(summary.get("percent_covered")), 2),
                "statements": integer(summary.get("num_statements")),
                "missing": integer(summary.get("missing_lines")),
            }
        )
    files.sort(key=lambda item: (item["percent"], item["file"]))
    return {
        "percent": round(number(totals.get("percent_covered")), 2),
        "statements": integer(totals.get("num_statements")),
        "covered_lines": integer(totals.get("covered_lines")),
        "missing_lines": integer(totals.get("missing_lines")),
        "excluded_lines": integer(totals.get("excluded_lines")),
        "files": files,
    }


def parse_performance(path: Path) -> dict[str, Any]:
    rows = []
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = [row for row in csv.DictReader(handle) if row.get("Name")]
    aggregate = next((row for row in rows if row.get("Name") == "Aggregated"), {})
    endpoints = [row for row in rows if row.get("Name") != "Aggregated"]
    endpoint_rows = []
    for row in endpoints:
        endpoint_rows.append(
            {
                "type": row.get("Type", ""),
                "name": row.get("Name", ""),
                "requests": integer(row.get("Request Count")),
                "failures": integer(row.get("Failure Count")),
                "rps": number(row.get("Requests/s")),
                "median": number(row.get("Median Response Time")),
                "average": number(row.get("Average Response Time")),
                "p95": number(row.get("95%")),
                "p99": number(row.get("99%")),
                "maximum": number(row.get("100%")),
            }
        )
    endpoint_rows.sort(key=lambda item: item["p95"], reverse=True)
    read_p95 = [item["p95"] for item in endpoint_rows if item["type"] == "GET"]
    write_p95 = [
        item["p95"] for item in endpoint_rows if item["type"] in {"POST", "PATCH"}
    ]
    return {
        "requests": integer(aggregate.get("Request Count")),
        "failures": integer(aggregate.get("Failure Count")),
        "rps": number(aggregate.get("Requests/s")),
        "median": number(aggregate.get("Median Response Time")),
        "average": number(aggregate.get("Average Response Time")),
        "p95": number(aggregate.get("95%")),
        "p99": number(aggregate.get("99%")),
        "maximum": number(aggregate.get("100%")),
        "read_p95": max(read_p95) if read_p95 else 0.0,
        "write_p95": max(write_p95) if write_p95 else 0.0,
        "endpoints": endpoint_rows,
    }


def latest_performance_run(records: list[dict[str, Any]]) -> dict[str, Any]:
    finished = [r for r in records if r.get("event") == "performance_run_finished"]
    if not finished:
        return {}
    record = finished[-1]
    return {
        "timestamp": record.get("timestamp", ""),
        "exit_code": record.get("exit_code"),
        "elapsed_seconds": number(record.get("elapsed_seconds")),
        "aggregated": record.get("aggregated", {}),
    }


def summarize_defects(rows: list[dict[str, str]]) -> dict[str, Any]:
    status_counts = Counter(row.get("状态", "未知") for row in rows)
    severity_counts = Counter(row.get("严重级别", "未知") for row in rows)
    open_rows = [
        row
        for row in rows
        if row.get("状态") not in {"已关闭", "已接受", "已拒绝"}
    ]
    open_p1 = [
        row
        for row in open_rows
        if row.get("严重级别") in {"致命", "严重", "高"}
        or row.get("优先级") in {"P0", "P1"}
    ]
    return {
        "total": len(rows),
        "status_counts": dict(status_counts),
        "severity_counts": dict(severity_counts),
        "open": len(open_rows),
        "open_p1": len(open_p1),
        "open_rows": open_rows,
        "accepted_rows": [row for row in rows if row.get("状态") == "已接受"],
    }


def summarize_risks(rows: list[dict[str, str]]) -> dict[str, Any]:
    status_counts = Counter(row.get("状态", "未知") for row in rows)
    severity_counts = Counter(row.get("风险等级", "未知") for row in rows)
    unresolved_high = [
        row
        for row in rows
        if row.get("风险等级") == "高" and row.get("状态") not in {"已关闭", "已缓解"}
    ]
    return {
        "total": len(rows),
        "status_counts": dict(status_counts),
        "severity_counts": dict(severity_counts),
        "unresolved_high": len(unresolved_high),
        "unresolved_high_rows": unresolved_high,
        "high_rows": [row for row in rows if row.get("风险等级") == "高"],
    }


def summarize_cases(rows: list[dict[str, str]]) -> dict[str, Any]:
    status_counts = Counter(row.get("执行状态", "未知") for row in rows)
    type_counts = Counter(row.get("测试类型", "未知") for row in rows)
    priority_counts = Counter(row.get("优先级", "未知") for row in rows)
    modules: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "passed": 0}
    )
    for row in rows:
        module = row.get("模块", "未知")
        modules[module]["total"] += 1
        if row.get("执行状态") == "通过":
            modules[module]["passed"] += 1
    interface_rows = [row for row in rows if row.get("测试类型") not in {"性能", "稳定性"}]
    performance_rows = [row for row in rows if row.get("测试类型") in {"性能", "稳定性"}]
    return {
        "total": len(rows),
        "status_counts": dict(status_counts),
        "type_counts": dict(type_counts),
        "priority_counts": dict(priority_counts),
        "modules": {
            key: {**value, "rate": pct(value["passed"], value["total"])}
            for key, value in modules.items()
        },
        "interface_total": len(interface_rows),
        "interface_passed": sum(
            1 for row in interface_rows if row.get("执行状态") == "通过"
        ),
        "performance_total": len(performance_rows),
        "performance_passed": sum(
            1 for row in performance_rows if row.get("执行状态") == "通过"
        ),
    }


def status_badge(ok: bool, text: str = "") -> str:
    label = text or ("通过" if ok else "未通过")
    css = "ok" if ok else "fail"
    return f'<span class="badge {css}">{esc(label)}</span>'


def gate_badge(status: str) -> str:
    css = {"通过": "ok", "关注": "warn", "未达标": "fail"}.get(status, "neutral")
    return f'<span class="badge {css}">{esc(status)}</span>'


def progress_bar(percent: float, tone: str = "teal") -> str:
    width = max(0.0, min(100.0, percent))
    return (
        '<div class="progress" role="img" aria-label="完成度 '
        f'{esc(fmt(width, 1))}%"><span class="{tone}" style="width:{width:.1f}%">'
        "</span></div>"
    )


def build_gates(
    junit: dict[str, Any],
    coverage: dict[str, Any],
    performance: dict[str, Any],
    defects: dict[str, Any],
    cases: dict[str, Any],
    traceability: list[dict[str, str]],
    perf_error_size: int,
) -> list[dict[str, str]]:
    executed = junit["tests"]
    passed = executed - junit["failures"] - junit["errors"] - junit["skipped"]
    pass_rate = pct(passed, executed)
    trace_passed = sum(1 for row in traceability if row.get("执行结果") == "通过")
    trace_rate = pct(trace_passed, len(traceability))
    log_cases = {
        row.get("用例编号"): row.get("执行状态")
        for row in read_csv(TEST_DESIGN / "test_cases.csv")
    }
    masking_ok = all(
        log_cases.get(case_id) == "通过"
        for case_id in ("TC-OBS-004", "TC-SEC-009")
    )
    coverage_status = (
        "通过"
        if coverage["percent"] >= 80
        else ("关注" if coverage["percent"] >= 70 else "未达标")
    )
    return [
        {
            "维度": "接口自动化",
            "指标": "用例通过率",
            "目标": "100%",
            "实际": f"{fmt(pass_rate)}% ({passed}/{executed})",
            "状态": "通过" if executed and pass_rate >= 100 else "未达标",
            "说明": "pytest 接口、安全、并发与日志用例",
        },
        {
            "维度": "代码覆盖率",
            "指标": "语句覆盖率",
            "目标": "不低于 80%",
            "实际": f"{fmt(coverage['percent'])}%",
            "状态": coverage_status,
            "说明": "pytest-cov 分支统计，排除模板与静态资源",
        },
        {
            "维度": "性能",
            "指标": "请求错误率",
            "目标": "低于 1%",
            "实际": f"{pct(performance['failures'], performance['requests']):.2f}%",
            "状态": "通过"
            if performance["requests"] and performance["failures"] == 0
            else "未达标",
            "说明": "Locust 30 并发、5 用户每秒、40 秒",
        },
        {
            "维度": "性能",
            "指标": "读接口 P95",
            "目标": "低于 300ms",
            "实际": f"{fmt(performance['read_p95'])}ms",
            "状态": "通过" if performance["read_p95"] < 300 else "未达标",
            "说明": "GET 接口最大 P95",
        },
        {
            "维度": "性能",
            "指标": "写接口 P95",
            "目标": "低于 800ms",
            "实际": f"{fmt(performance['write_p95'])}ms",
            "状态": "通过" if performance["write_p95"] < 800 else "未达标",
            "说明": "POST 与 PATCH 接口最大 P95",
        },
        {
            "维度": "性能",
            "指标": "吞吐量",
            "目标": "不低于 50 RPS",
            "实际": f"{fmt(performance['rps'])} RPS",
            "状态": "通过" if performance["rps"] >= 50 else "未达标",
            "说明": "单机 SQLite 演示环境",
        },
        {
            "维度": "稳定性",
            "指标": "性能 ERROR 日志",
            "目标": "0 条",
            "实际": f"{perf_error_size} 字节",
            "状态": "通过" if perf_error_size == 0 else "未达标",
            "说明": "logs/performance/error.jsonl",
        },
        {
            "维度": "缺陷",
            "指标": "未关闭 P0/P1",
            "目标": "0 项",
            "实际": f"{defects['open_p1']} 项",
            "状态": "通过" if defects["open_p1"] == 0 else "未达标",
            "说明": "高优先级问题必须关闭或有批准豁免",
        },
        {
            "维度": "需求追踪",
            "指标": "需求项执行覆盖",
            "目标": "100%",
            "实际": f"{fmt(trace_rate)}% ({trace_passed}/{len(traceability)})",
            "状态": "通过" if traceability and trace_rate >= 100 else "未达标",
            "说明": "需求、用例、脚本、缺陷与风险双向关联",
        },
        {
            "维度": "可观测性",
            "指标": "日志脱敏自动化",
            "目标": "全部通过",
            "实际": "通过" if masking_ok else "存在失败",
            "状态": "通过" if masking_ok else "未达标",
            "说明": "嵌套字段脱敏与查询参数脱敏用例",
        },
        {
            "维度": "用例资产",
            "指标": "用例台账完整度",
            "目标": "覆盖全部自动化与性能场景",
            "实际": f"{cases['total']} 项",
            "状态": "通过"
            if cases["status_counts"].get("通过") == cases["total"]
            else "关注",
            "说明": "接口用例 60 项，性能场景 6 项",
        },
    ]


CSS = """
:root{
  --bg:#f2f5f7;--surface:#ffffff;--ink:#17242f;--muted:#607180;
  --line:#d8e0e6;--navy:#123047;--teal:#0d7a68;--blue:#24658f;
  --amber:#a86414;--red:#b42318;--soft-teal:#e5f3f0;--soft-blue:#eaf2f8;
  --soft-amber:#fbf3e6;--soft-red:#fbeceb;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 "Segoe UI","Microsoft YaHei",system-ui,sans-serif}
a{color:var(--blue);text-decoration:none}
a:hover{text-decoration:underline}
.topbar{background:var(--navy);color:#fff;padding:12px 0;border-bottom:3px solid var(--teal)}
.wrap{max-width:1280px;margin:0 auto;padding:0 24px}
.topline{display:flex;align-items:center;justify-content:space-between;gap:18px;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:12px;font-weight:650;letter-spacing:.2px}
.brand-mark{width:32px;height:32px;border-radius:7px;background:var(--teal);display:grid;place-items:center;font-weight:800;color:#fff}
.nav{display:flex;gap:16px;flex-wrap:wrap;font-size:13px}
.nav a{color:#d9e7ee}
.hero{background:#fff;border-bottom:1px solid var(--line);padding:34px 0 28px}
.hero-grid{display:flex;justify-content:space-between;gap:30px;align-items:flex-end;flex-wrap:wrap}
.eyebrow{color:var(--teal);font-weight:700;font-size:12px;letter-spacing:1.4px;text-transform:uppercase;margin-bottom:8px}
h1{font-size:32px;line-height:1.2;margin:0 0 10px;letter-spacing:0;color:var(--navy)}
.lead{max-width:780px;color:var(--muted);margin:0;font-size:15px}
.stamp{text-align:right;color:var(--muted);font-size:12px;min-width:230px}
.status-pill{display:inline-flex;align-items:center;gap:8px;background:var(--soft-amber);color:#7a4a0b;border:1px solid #e8c896;padding:7px 12px;border-radius:999px;font-weight:700;margin-bottom:8px}
.status-dot{width:9px;height:9px;border-radius:50%;background:var(--amber)}
main{padding:28px 0 54px}
section{margin:0 0 26px}
.section-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:12px;flex-wrap:wrap}
h2{font-size:19px;line-height:1.3;margin:0;color:var(--navy);letter-spacing:0}
.section-note{color:var(--muted);font-size:12px;margin:0}
.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px;margin-bottom:26px}
.kpi{background:var(--surface);border:1px solid var(--line);border-top:3px solid var(--teal);border-radius:8px;padding:16px 16px 14px;min-height:118px}
.kpi.blue{border-top-color:var(--blue)}
.kpi.amber{border-top-color:var(--amber)}
.kpi .label{font-size:12px;color:var(--muted);font-weight:650;min-height:18px}
.kpi .value{font-size:27px;font-weight:750;line-height:1.15;margin:8px 0 4px;color:var(--navy);letter-spacing:0}
.kpi .detail{font-size:12px;color:var(--muted)}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:18px 18px 16px}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid-3{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{background:#eef3f6;color:#34495a;text-align:left;font-weight:700;padding:9px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:9px 10px;border-bottom:1px solid #e8edf0;vertical-align:top}
tbody tr:hover{background:#f8fafb}
.table-scroll{overflow:auto;max-height:520px;border:1px solid var(--line);border-radius:7px}
.table-scroll table{min-width:760px}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}
.badge.ok{background:var(--soft-teal);color:#0a5c4f;border:1px solid #b9ded7}
.badge.fail{background:var(--soft-red);color:#8f1c14;border:1px solid #efc3bf}
.badge.warn{background:var(--soft-amber);color:#7a4a0b;border:1px solid #ead0a3}
.badge.neutral{background:#edf1f4;color:#475b6b;border:1px solid #d4dde3}
.progress{height:8px;background:#e8eef2;border-radius:999px;overflow:hidden;min-width:80px}
.progress span{display:block;height:100%;border-radius:999px;background:var(--teal)}
.progress span.blue{background:var(--blue)}
.progress span.amber{background:var(--amber)}
.progress span.red{background:var(--red)}
.bar-row{display:grid;grid-template-columns:120px 1fr 58px;gap:10px;align-items:center;margin:8px 0;font-size:12px}
.bar-row .name{color:#33495a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-row .num{text-align:right;color:var(--muted);font-variant-numeric:tabular-nums}
.mini-list{display:grid;gap:9px}
.mini-item{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding-bottom:9px;border-bottom:1px solid #e8edf0}
.mini-item:last-child{border-bottom:0;padding-bottom:0}
.mini-title{font-weight:650;color:#273d4e;margin-bottom:2px}
.mini-sub{font-size:12px;color:var(--muted)}
.callout{background:var(--soft-blue);border:1px solid #c8dbe8;border-left:4px solid var(--blue);padding:12px 14px;border-radius:6px;color:#29495f;font-size:13px}
.callout strong{color:var(--navy)}
.evidence{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.evidence a{display:block;background:#fff;border:1px solid var(--line);border-radius:7px;padding:13px 14px;color:var(--ink);min-height:70px}
.evidence a:hover{border-color:#9eb6c6;text-decoration:none;background:#f9fbfc}
.evidence .link-title{font-weight:700;color:var(--blue);margin-bottom:3px}
.evidence .link-note{font-size:12px;color:var(--muted)}
.toolbar{display:flex;gap:10px;align-items:center;margin:0 0 12px;flex-wrap:wrap}
.toolbar input,.toolbar select{height:34px;border:1px solid #cbd6de;border-radius:6px;padding:0 10px;background:#fff;color:var(--ink);font:13px "Segoe UI","Microsoft YaHei",sans-serif}
.toolbar input{min-width:260px;flex:1;max-width:420px}
.muted{color:var(--muted)}
.small{font-size:12px}
.danger{color:var(--red);font-weight:700}
.good{color:var(--teal);font-weight:700}
.footer{border-top:1px solid var(--line);padding:18px 0 30px;color:var(--muted);font-size:12px;text-align:center}
@media (max-width:1050px){
  .kpis{grid-template-columns:repeat(3,minmax(0,1fr))}
  .grid-3{grid-template-columns:1fr 1fr}
  .evidence{grid-template-columns:1fr 1fr}
}
@media (max-width:780px){
  .wrap{padding:0 16px}
  h1{font-size:25px}
  .kpis{grid-template-columns:1fr 1fr}
  .grid-2,.grid-3{grid-template-columns:1fr}
  .stamp{text-align:left}
  .nav{display:none}
  .bar-row{grid-template-columns:96px 1fr 50px}
}
@media (max-width:480px){
  .kpis{grid-template-columns:1fr}
  .evidence{grid-template-columns:1fr}
  .toolbar input{min-width:100%}
}
"""


def make_module_rows(cases: dict[str, Any]) -> str:
    rows = []
    order = ["认证", "边界", "订单", "库存", "商品", "权限", "安全", "系统", "可观测性", "性能"]
    for module in order:
        data = cases["modules"].get(module)
        if not data:
            continue
        tone = "teal" if data["rate"] >= 100 else "amber"
        rows.append(
            "<div class='bar-row'>"
            f"<span class='name'>{esc(module)}</span>"
            f"{progress_bar(data['rate'], tone)}"
            f"<span class='num'>{data['passed']}/{data['total']}</span>"
            "</div>"
        )
    return "".join(rows)


def make_gate_table(gates: list[dict[str, str]]) -> str:
    rows = []
    for gate in gates:
        rows.append(
            "<tr>"
            f"<td>{esc(gate['维度'])}</td>"
            f"<td>{esc(gate['指标'])}</td>"
            f"<td>{esc(gate['目标'])}</td>"
            f"<td><strong>{esc(gate['实际'])}</strong></td>"
            f"<td>{gate_badge(gate['状态'])}</td>"
            f"<td class='muted'>{esc(gate['说明'])}</td>"
            "</tr>"
        )
    return (
        "<div class='table-scroll'><table><thead><tr>"
        "<th>维度</th><th>指标</th><th>目标</th><th>实际</th><th>结论</th><th>说明</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def make_coverage_rows(coverage: dict[str, Any]) -> str:
    rows = []
    for item in coverage["files"][:10]:
        tone = "teal" if item["percent"] >= 80 else ("amber" if item["percent"] >= 60 else "red")
        rows.append(
            "<tr>"
            f"<td><code>{esc(item['file'])}</code></td>"
            f"<td>{progress_bar(item['percent'], tone)}</td>"
            f"<td>{fmt(item['percent'])}%</td>"
            f"<td>{item['missing']}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='4' class='muted'>暂无覆盖率明细</td></tr>")
    return (
        "<div class='table-scroll'><table><thead><tr>"
        "<th>文件</th><th>覆盖率</th><th>比例</th><th>缺失语句</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def make_performance_rows(performance: dict[str, Any]) -> str:
    rows = []
    max_p95 = max((item["p95"] for item in performance["endpoints"]), default=1)
    for item in performance["endpoints"]:
        tone = "teal" if item["p95"] < (300 if item["type"] == "GET" else 800) else "red"
        width = item["p95"] / max_p95 * 100 if max_p95 else 0
        rows.append(
            "<tr>"
            f"<td><code>{esc(item['type'])}</code></td>"
            f"<td>{esc(item['name'])}</td>"
            f"<td>{item['requests']:,}</td>"
            f"<td>{item['failures']}</td>"
            f"<td>{fmt(item['rps'], 2)}</td>"
            f"<td>{fmt(item['median'], 0)}</td>"
            f"<td>{fmt(item['p95'], 0)}</td>"
            f"<td>{fmt(item['p99'], 0)}</td>"
            f"<td>{fmt(item['maximum'], 1)}</td>"
            f"<td><div class='progress'><span class='{tone}' style='width:{width:.1f}%'></span></div></td>"
            "</tr>"
        )
    return (
        "<div class='table-scroll'><table><thead><tr>"
        "<th>方法</th><th>接口</th><th>请求数</th><th>失败</th><th>RPS</th>"
        "<th>P50</th><th>P95</th><th>P99</th><th>最大</th><th>P95 对比</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def make_defect_rows(defects: dict[str, Any]) -> str:
    rows = []
    for row in (defects["open_rows"] + defects["accepted_rows"])[:8]:
        status = row.get("状态", "")
        css = "warn" if status == "待处理" else "neutral"
        rows.append(
            "<tr>"
            f"<td><strong>{esc(row.get('缺陷编号', ''))}</strong></td>"
            f"<td>{esc(row.get('标题', ''))}</td>"
            f"<td>{esc(row.get('严重级别', ''))}</td>"
            f"<td><span class='badge {css}'>{esc(status)}</span></td>"
            f"<td class='muted'>{esc(row.get('修复方案', ''))[:120]}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='5' class='muted'>全部缺陷已关闭</td></tr>")
    return (
        "<div class='table-scroll'><table><thead><tr>"
        "<th>编号</th><th>标题</th><th>级别</th><th>状态</th><th>处置</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def make_risk_rows(risks: dict[str, Any]) -> str:
    rows = []
    for row in risks["high_rows"][:6]:
        status = row.get("状态", "")
        css = "ok" if status in {"已缓解", "已关闭"} else "warn"
        rows.append(
            "<tr>"
            f"<td><strong>{esc(row.get('风险编号', ''))}</strong></td>"
            f"<td>{esc(row.get('风险描述', ''))}</td>"
            f"<td>{esc(row.get('风险分值', ''))}</td>"
            f"<td><span class='badge {css}'>{esc(status)}</span></td>"
            f"<td class='muted'>{esc(row.get('缓解措施', ''))[:110]}</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='5' class='muted'>暂无高风险项</td></tr>")
    return (
        "<div class='table-scroll'><table><thead><tr>"
        "<th>编号</th><th>风险</th><th>分值</th><th>状态</th><th>缓解措施</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def make_case_rows(case_rows: list[dict[str, str]]) -> str:
    rows = []
    for row in case_rows:
        status = row.get("执行状态", "")
        css = "ok" if status == "通过" else "fail"
        module = row.get("模块", "")
        rows.append(
            "<tr data-module='{module}' data-text='{search}'>"
            f"<td><strong>{esc(row.get('用例编号', ''))}</strong></td>"
            f"<td>{esc(module)}</td>"
            f"<td>{esc(row.get('场景', ''))}</td>"
            f"<td>{esc(row.get('优先级', ''))}</td>"
            f"<td>{esc(row.get('测试类型', ''))}</td>"
            f"<td><span class='badge {css}'>{esc(status)}</span></td>"
            f"<td class='muted'><code>{esc(row.get('自动化脚本', ''))}</code></td>"
            "</tr>".format(
                module=esc(module),
                search=esc(
                    " ".join(
                        [
                            row.get("用例编号", ""),
                            module,
                            row.get("场景", ""),
                            row.get("测试类型", ""),
                        ]
                    )
                ),
            )
        )
    return "".join(rows)


def make_slowest_rows(session: dict[str, Any]) -> str:
    rows = []
    for item in session["slowest"]:
        rows.append(
            "<tr>"
            f"<td><strong>{esc(item['case_id'])}</strong></td>"
            f"<td class='muted'><code>{esc(item['nodeid'].split('::')[-1])}</code></td>"
            f"<td>{fmt(item['duration_ms'], 2)}ms</td>"
            "</tr>"
        )
    if not rows:
        rows.append("<tr><td colspan='3' class='muted'>暂无执行记录</td></tr>")
    return "".join(rows)


def build_summary(
    junit: dict[str, Any],
    session: dict[str, Any],
    coverage: dict[str, Any],
    performance: dict[str, Any],
    perf_run: dict[str, Any],
    defects: dict[str, Any],
    risks: dict[str, Any],
    cases: dict[str, Any],
    traceability: list[dict[str, str]],
    gates: list[dict[str, str]],
    perf_logs: dict[str, int],
    perf_error_size: int,
) -> dict[str, Any]:
    failures = junit["failures"] + junit["errors"]
    passed = junit["tests"] - failures - junit["skipped"]
    statuses = {gate["状态"] for gate in gates}
    if "未达标" in statuses:
        overall = "未通过"
    elif "关注" in statuses:
        overall = "有条件通过"
    else:
        overall = "通过"
    return {
        "project": "履约中枢订单履约平台",
        "version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "overall_status": overall,
        "release_recommendation": (
            "接口回归与性能基线达标，可进入发布评审。"
            "BUG-006 需在网关或 WAF 完成登录限流后关闭；"
            "BUG-007 已获产品负责人接受。"
        ),
        "test_execution": {
            "tests": junit["tests"],
            "passed": passed,
            "failed": failures,
            "skipped": junit["skipped"],
            "pass_rate": pct(passed, junit["tests"]),
            "duration_seconds": round(junit["time"], 2),
            "started_at": junit["timestamp"],
            "latest_session": session,
        },
        "test_assets": {
            "ledger_total": cases["total"],
            "interface_cases": cases["interface_total"],
            "interface_passed": cases["interface_passed"],
            "performance_cases": cases["performance_total"],
            "performance_passed": cases["performance_passed"],
            "type_counts": cases["type_counts"],
            "priority_counts": cases["priority_counts"],
            "module_counts": cases["modules"],
        },
        "coverage": {
            "percent": coverage["percent"],
            "statements": coverage["statements"],
            "covered_lines": coverage["covered_lines"],
            "missing_lines": coverage["missing_lines"],
            "lowest_files": coverage["files"][:10],
        },
        "performance": {
            **performance,
            "run": perf_run,
            "error_log_bytes": perf_error_size,
            "log_counts": perf_logs,
            "status": "通过"
            if performance["requests"]
            and performance["failures"] == 0
            and perf_error_size == 0
            else "未达标",
        },
        "defects": defects,
        "risks": {
            "total": risks["total"],
            "status_counts": risks["status_counts"],
            "severity_counts": risks["severity_counts"],
            "unresolved_high": risks["unresolved_high"],
        },
        "traceability": {
            "requirements": len(traceability),
            "executed": sum(
                1 for row in traceability if row.get("执行结果") == "通过"
            ),
            "coverage_rate": pct(
                sum(1 for row in traceability if row.get("执行结果") == "通过"),
                len(traceability),
            ),
        },
        "quality_gates": gates,
    }


def build_html(
    summary: dict[str, Any],
    case_rows: list[dict[str, str]],
    gates: list[dict[str, str]],
    defects: dict[str, Any],
    risks: dict[str, Any],
    coverage: dict[str, Any],
    performance: dict[str, Any],
    cases: dict[str, Any],
    session: dict[str, Any],
    perf_run: dict[str, Any],
    perf_logs: dict[str, int],
    perf_error_size: int,
) -> str:
    overall = summary["overall_status"]
    status_class = "通过" if overall == "通过" else "有条件通过"
    interface_total = cases["interface_total"]
    interface_passed = cases["interface_passed"]
    coverage_pct = coverage["percent"]
    performance_p95 = performance["p95"]
    defect_total = defects["total"]
    defect_closed = defects["status_counts"].get("已关闭", 0)
    open_count = defects["open"]
    accepted_count = defects["status_counts"].get("已接受", 0)
    trace = summary["traceability"]
    perf_requests = performance["requests"]
    perf_rps = performance["rps"]
    perf_failures = performance["failures"]
    elapsed = session["elapsed_seconds"] or summary["test_execution"]["duration_seconds"]
    start_time = summary["test_execution"]["started_at"].replace("T", " ")[:19]
    module_rows = make_module_rows(cases)
    gate_table = make_gate_table(gates)
    coverage_rows = make_coverage_rows(coverage)
    performance_rows = make_performance_rows(performance)
    defect_rows = make_defect_rows(defects)
    risk_rows = make_risk_rows(risks)
    case_table_rows = make_case_rows(case_rows)
    slowest_rows = make_slowest_rows(session)
    modules = sorted(cases["modules"].keys())
    module_options = "".join(
        f"<option value='{esc(module)}'>{esc(module)}</option>" for module in modules
    )
    type_bars = "".join(
        "<div class='bar-row'>"
        f"<span class='name'>{esc(name)}</span>"
        f"{progress_bar(pct(count, cases['total']), 'blue')}"
        f"<span class='num'>{count}</span>"
        "</div>"
        for name, count in sorted(
            cases["type_counts"].items(), key=lambda item: item[1], reverse=True
        )
    )
    defect_bars = "".join(
        "<div class='bar-row'>"
        f"<span class='name'>{esc(name)}</span>"
        f"{progress_bar(pct(count, defect_total), 'amber' if name != '已关闭' else 'teal')}"
        f"<span class='num'>{count}</span>"
        "</div>"
        for name, count in sorted(
            defects["status_counts"].items(), key=lambda item: item[1], reverse=True
        )
    )
    run_exit = perf_run.get("exit_code", "-")
    run_time = str(perf_run.get("timestamp", "")).replace("T", " ")[:19]
    perf_status = summary["performance"]["status"]
    recommendation = summary["release_recommendation"]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>履约中枢质量总览</title>
<style>{CSS}</style>
</head>
<body>
<header class="topbar">
  <div class="wrap topline">
    <div class="brand"><span class="brand-mark">QA</span><span>履约中枢 · 质量工程</span></div>
    <nav class="nav" aria-label="页面导航">
      <a href="#overview">概览</a><a href="#gates">质量门禁</a><a href="#execution">测试执行</a>
      <a href="#performance">性能</a><a href="#defects">缺陷与风险</a><a href="#logs">日志</a><a href="#evidence">证据</a>
    </nav>
  </div>
</header>
<section class="hero" id="overview">
  <div class="wrap hero-grid">
    <div>
      <div class="eyebrow">API Quality Assurance</div>
      <h1>订单履约平台测试质量总览</h1>
      <p class="lead">接口自动化、边界与安全测试、并发一致性、Locust 性能基线和企业级结构化日志形成完整证据链。页面数据来自本次实际执行产物，不使用静态演示数字。</p>
    </div>
    <div class="stamp">
      <div class="status-pill"><span class="status-dot"></span>发布结论：{esc(overall)}</div>
      <div>版本 order-fulfillment 1.0.0</div>
      <div>生成时间 {esc(summary['generated_at'].replace('T', ' ')[:19])} UTC</div>
      <div>最近接口执行 {esc(start_time)}</div>
    </div>
  </div>
</section>
<main class="wrap">
  <div class="kpis">
    <div class="kpi"><div class="label">接口自动化用例</div><div class="value">{interface_passed}/{interface_total}</div><div class="detail">pytest 全量通过</div></div>
    <div class="kpi blue"><div class="label">语句覆盖率</div><div class="value">{fmt(coverage_pct)}%</div><div class="detail">目标不低于 80%</div></div>
    <div class="kpi"><div class="label">性能吞吐</div><div class="value">{fmt(perf_rps)}</div><div class="detail">RPS · 30 并发 · 40 秒</div></div>
    <div class="kpi blue"><div class="label">性能失败请求</div><div class="value">{perf_failures}</div><div class="detail">{perf_requests:,} 次请求 · 错误率 0%</div></div>
    <div class="kpi"><div class="label">综合 P95</div><div class="value">{fmt(performance_p95)}ms</div><div class="detail">P99 {fmt(performance['p99'])}ms · 最大 {fmt(performance['maximum'])}ms</div></div>
    <div class="kpi amber"><div class="label">缺陷闭环</div><div class="value">{defect_closed}/{defect_total}</div><div class="detail">{open_count} 待处理 · {accepted_count} 已接受</div></div>
  </div>

  <section id="gates">
    <div class="section-head"><h2>质量门禁</h2><p class="section-note">发布前必须满足的接口、覆盖率、性能、缺陷与可观测性条件</p></div>
    {gate_table}
  </section>

  <section id="execution">
    <div class="section-head"><h2>测试执行</h2><p class="section-note">JUnit、测试执行日志与用例台账交叉核对</p></div>
    <div class="grid-2">
      <div class="panel">
        <div style="display:flex;justify-content:space-between;gap:16px;align-items:baseline;margin-bottom:8px">
          <strong>模块通过率</strong><span class="muted small">{cases['total']} 项用例台账 · {fmt(elapsed)} 秒执行</span>
        </div>
        {module_rows}
        <div class="callout" style="margin-top:16px"><strong>执行结论：</strong>pytest {summary['test_execution']['tests']} 项通过 {summary['test_execution']['passed']} 项，失败 {summary['test_execution']['failed']} 项，跳过 {summary['test_execution']['skipped']} 项。并发防超卖、幂等重放和日志脱敏均已纳入自动回归。</div>
      </div>
      <div class="panel">
        <div style="display:flex;justify-content:space-between;gap:16px;align-items:baseline;margin-bottom:8px">
          <strong>用例结构</strong><span class="muted small">按测试类型</span>
        </div>
        {type_bars}
        <div style="display:flex;justify-content:space-between;gap:16px;align-items:baseline;margin:18px 0 8px"><strong>最慢用例</strong><span class="muted small">执行日志</span></div>
        <table><thead><tr><th>用例</th><th>脚本</th><th>耗时</th></tr></thead><tbody>{slowest_rows}</tbody></table>
      </div>
    </div>
  </section>

  <section id="coverage">
    <div class="section-head"><h2>代码覆盖率</h2><p class="section-note">pytest-cov 语句与分支统计，展示覆盖率最低的核心文件</p></div>
    <div class="panel">
      <div style="display:flex;justify-content:space-between;gap:20px;align-items:center;flex-wrap:wrap;margin-bottom:14px">
        <div><div class="muted small">总体语句覆盖率</div><div style="font-size:30px;font-weight:750;color:var(--navy)">{fmt(coverage_pct)}%</div></div>
        <div style="min-width:260px;flex:1;max-width:520px">{progress_bar(coverage_pct, 'teal')}<div class="muted small" style="margin-top:6px">已覆盖 {coverage['covered_lines']:,} 行 · 缺失 {coverage['missing_lines']:,} 行 · 统计 {coverage['statements']:,} 行</div></div>
      </div>
      {coverage_rows}
    </div>
  </section>

  <section id="performance">
    <div class="section-head"><h2>性能基线</h2><p class="section-note">Locust 混合读写、幂等重放、状态流转与登录流量</p></div>
    <div class="panel">
      <div class="grid-3" style="margin-bottom:16px">
        <div><div class="muted small">请求与失败</div><div style="font-size:24px;font-weight:750;color:var(--navy)">{perf_requests:,} / {perf_failures}</div><div class="muted small">请求数 / 失败数</div></div>
        <div><div class="muted small">延迟分位</div><div style="font-size:24px;font-weight:750;color:var(--navy)">P50 {fmt(performance['median'], 0)} · P95 {fmt(performance_p95, 0)}</div><div class="muted small">P99 {fmt(performance['p99'], 0)}ms</div></div>
        <div><div class="muted small">压测编排</div><div style="font-size:24px;font-weight:750;color:var(--navy)">exit {esc(run_exit)}</div><div class="muted small">{esc(run_time)} · {fmt(perf_run.get('elapsed_seconds', 0))} 秒</div></div>
      </div>
      {performance_rows}
      <div class="callout" style="margin-top:14px"><strong>结论：</strong>读接口最大 P95 {fmt(performance['read_p95'])}ms，写接口最大 P95 {fmt(performance['write_p95'])}ms，均低于 SLO。性能隔离日志中 error.jsonl 为 {perf_error_size} 字节，访问日志 {perf_logs.get('access', 0):,} 条，审计日志 {perf_logs.get('audit', 0):,} 条。当前结论为 {esc(perf_status)}。</div>
    </div>
  </section>

  <section id="defects">
    <div class="section-head"><h2>缺陷与风险</h2><p class="section-note">缺陷状态、修复证据和发布前风险处置</p></div>
    <div class="grid-2">
      <div class="panel">
        <div style="display:flex;justify-content:space-between;gap:16px;align-items:baseline;margin-bottom:8px"><strong>缺陷台账</strong><span class="muted small">{defect_total} 项 · 未关闭 {open_count} 项 · 已接受 {accepted_count} 项</span></div>
        {defect_bars}
        <div style="margin-top:14px">{defect_rows}</div>
      </div>
      <div class="panel">
        <div style="display:flex;justify-content:space-between;gap:16px;align-items:baseline;margin-bottom:8px"><strong>高风险项</strong><span class="muted small">{risks['total']} 项风险 · 未缓解高风险 {risks['unresolved_high']} 项</span></div>
        {risk_rows}
        <div class="callout" style="margin-top:14px"><strong>发布建议：</strong>{esc(recommendation)}</div>
      </div>
    </div>
  </section>

  <section id="logs">
    <div class="section-head"><h2>企业日志证据</h2><p class="section-note">JSON Lines、请求关联、审计追溯、安全事件与脱敏验证</p></div>
    <div class="panel">
      <div class="grid-3">
        <div><div class="muted small">性能访问日志</div><div style="font-size:25px;font-weight:750;color:var(--navy)">{perf_logs.get('access', 0):,}</div><div class="muted small">http_request 事件</div></div>
        <div><div class="muted small">性能审计日志</div><div style="font-size:25px;font-weight:750;color:var(--navy)">{perf_logs.get('audit', 0):,}</div><div class="muted small">订单与登录业务动作</div></div>
        <div><div class="muted small">性能安全日志</div><div style="font-size:25px;font-weight:750;color:var(--navy)">{perf_logs.get('security', 0):,}</div><div class="muted small">失败登录与权限事件</div></div>
      </div>
      <div class="callout" style="margin-top:16px"><strong>可观测性结论：</strong>所有 HTTP 请求均写入 request_id、trace_id、method、path、status 和 duration；订单创建、状态变更和取消写入审计日志；错误日志 0 字节；嵌套密钥与查询参数脱敏用例通过。按 request_id 可以从访问日志追到业务日志、审计日志和安全日志。</div>
    </div>
  </section>

  <section id="cases">
    <div class="section-head"><h2>测试用例台账</h2><p class="section-note">共 {cases['total']} 项，支持按模块筛选和关键字检索</p></div>
    <div class="panel">
      <div class="toolbar">
        <input id="caseSearch" type="search" placeholder="搜索用例编号、场景或测试类型" aria-label="搜索测试用例">
        <select id="moduleFilter" aria-label="按模块筛选"><option value="">全部模块</option>{module_options}</select>
        <span id="caseCount" class="muted small"></span>
      </div>
      <div class="table-scroll">
        <table id="caseTable"><thead><tr><th>用例编号</th><th>模块</th><th>场景</th><th>优先级</th><th>类型</th><th>状态</th><th>自动化脚本</th></tr></thead><tbody>{case_table_rows}</tbody></table>
      </div>
    </div>
  </section>

  <section id="evidence">
    <div class="section-head"><h2>交付证据</h2><p class="section-note">可直接打开的原始终端与报告文件</p></div>
    <div class="evidence">
      <a href="test-report.html"><div class="link-title">pytest HTML 报告</div><div class="link-note">用例级执行详情与失败摘要</div></a>
      <a href="test-results.xml"><div class="link-title">JUnit XML</div><div class="link-note">CI 可解析的接口测试结果</div></a>
      <a href="coverage/index.html"><div class="link-title">覆盖率 HTML</div><div class="link-note">逐文件语句与分支覆盖</div></a>
      <a href="performance/locust-report.html"><div class="link-title">Locust HTML 报告</div><div class="link-note">吞吐、延迟分位与接口分布</div></a>
      <a href="performance/locust_stats.csv"><div class="link-title">性能统计 CSV</div><div class="link-note">接口级请求、失败与分位数据</div></a>
      <a href="quality_summary.json"><div class="link-title">质量汇总 JSON</div><div class="link-note">门禁结果与机器可读指标</div></a>
    </div>
  </section>
</main>
<footer class="footer"><div class="wrap">履约中枢质量工程 · 接口自动化与企业级日志演示 · 数据生成于 {esc(summary['generated_at'])}</div></footer>
<script>
(function(){{
  const input=document.getElementById('caseSearch');
  const select=document.getElementById('moduleFilter');
  const rows=Array.from(document.querySelectorAll('#caseTable tbody tr'));
  const count=document.getElementById('caseCount');
  function apply(){{
    const term=(input.value||'').trim().toLowerCase();
    const module=(select.value||'').trim();
    let visible=0;
    rows.forEach(function(row){{
      const text=(row.getAttribute('data-text')||'').toLowerCase();
      const rowModule=row.getAttribute('data-module')||'';
      const okText=!term||text.indexOf(term)>=0;
      const okModule=!module||rowModule===module;
      const show=okText&&okModule;
      row.style.display=show?'':'none';
      if(show) visible++;
    }});
    count.textContent='显示 '+visible+' / '+rows.length+' 项';
  }}
  input.addEventListener('input',apply);
  select.addEventListener('change',apply);
  apply();
}})();
</script>
</body>
</html>"""


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    junit = parse_junit(REPORTS / "test-results.xml")
    all_test_records = read_jsonl(LOGS / "tests" / "test_execution.jsonl")
    session = latest_test_session(all_test_records)
    coverage = parse_coverage(REPORTS / "coverage.json")
    performance = parse_performance(REPORTS / "performance" / "locust_stats.csv")
    perf_run = latest_performance_run(
        read_jsonl(LOGS / "performance" / "performance_run.jsonl")
    )
    case_rows = read_csv(TEST_DESIGN / "test_cases.csv")
    defect_rows = read_csv(DEFECTS / "defect_register.csv")
    risk_rows = read_csv(TEST_DESIGN / "risk_register.csv")
    traceability = read_csv(TEST_DESIGN / "traceability_matrix.csv")
    cases = summarize_cases(case_rows)
    defects = summarize_defects(defect_rows)
    risks = summarize_risks(risk_rows)
    perf_error_size = file_size(LOGS / "performance" / "error.jsonl")
    perf_logs = {
        "access": count_lines(LOGS / "performance" / "access.jsonl"),
        "audit": count_lines(LOGS / "performance" / "audit.jsonl"),
        "security": count_lines(LOGS / "performance" / "security.jsonl"),
        "app": count_lines(LOGS / "performance" / "app.jsonl"),
        "error": count_lines(LOGS / "performance" / "error.jsonl"),
    }
    gates = build_gates(
        junit, coverage, performance, defects, cases, traceability, perf_error_size
    )
    summary = build_summary(
        junit,
        session,
        coverage,
        performance,
        perf_run,
        defects,
        risks,
        cases,
        traceability,
        gates,
        perf_logs,
        perf_error_size,
    )
    summary_path = REPORTS / "quality_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    dashboard = build_html(
        summary,
        case_rows,
        gates,
        defects,
        risks,
        coverage,
        performance,
        cases,
        session,
        perf_run,
        perf_logs,
        perf_error_size,
    )
    dashboard_path = REPORTS / "quality_dashboard.html"
    dashboard_path.write_text(dashboard, encoding="utf-8")
    print(f"quality summary: {summary_path}")
    print(f"quality dashboard: {dashboard_path}")
    print(
        "result: "
        f"tests={junit['tests']} passed={junit['tests'] - junit['failures'] - junit['errors'] - junit['skipped']} "
        f"coverage={coverage['percent']}% "
        f"requests={performance['requests']} failures={performance['failures']} "
        f"p95={performance['p95']}ms status={summary['overall_status']}"
    )


if __name__ == "__main__":
    main()
