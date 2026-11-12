"""Build a workbook-ready JSON snapshot from the executed QA artifacts."""

from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
LOGS = ROOT / "logs"
TEST_DESIGN = ROOT / "test_design"
DEFECTS = ROOT / "defect_management"
OUTPUT = ROOT / "artifacts" / "quality_workbook_data.json"

DEMO_SECRETS = ("Admin@123", "Operator@123", "Viewer@123", "local-dev-secret")
SENSITIVE_TEXT = re.compile(
    r"(?i)(password|passwd|pwd|token|authorization|secret|api[_-]?key)"
    r"([\"']?\s*[:=]\s*)([\"']?)[^\"'\s,&；}]+"
)
BEARER_TEXT = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*")
JWT_TEXT = re.compile(
    r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def mask_text(value: Any) -> str:
    text = str(value)
    for secret in DEMO_SECRETS:
        text = text.replace(secret, "***")
    text = BEARER_TEXT.sub("Bearer ***", text)
    text = SENSITIVE_TEXT.sub(r"\1\2\3***", text)
    return JWT_TEXT.sub("***", text)


def mask_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {key: mask_text(value) for key, value in row.items()}
        for row in rows
    ]


def parse_junit(path: Path) -> list[dict[str, Any]]:
    root = ET.parse(path).getroot()
    cases: list[dict[str, Any]] = []
    for case in root.iter("testcase"):
        classname = case.attrib.get("classname", "")
        name = case.attrib.get("name", "")
        nodeid = f"{classname.replace('.', '/')}.py::{name}"
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")
        status = "通过"
        detail = ""
        if failure is not None or error is not None:
            status = "失败"
            node = failure if failure is not None else error
            detail = (node.attrib.get("message") or node.text or "")[:500]
        elif skipped is not None:
            status = "跳过"
            detail = skipped.attrib.get("message", "")
        cases.append(
            {
                "nodeid": nodeid,
                "name": name,
                "result": status,
                "duration_ms": round(float(case.attrib.get("time", 0)) * 1000, 2),
                "detail": mask_text(detail),
            }
        )
    return cases


def latest_session(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    start_index = 0
    for index, record in enumerate(records):
        if record.get("event") == "test_session_started":
            start_index = index
    session = records[start_index:]
    finished = [record for record in session if record.get("event") == "test_finished"]
    end_record = next(
        (record for record in reversed(session) if record.get("event") == "test_session_finished"),
        {},
    )
    start_record = session[0] if session else {}
    return finished, {"start": start_record, "end": end_record}


def build_execution_rows(
    junit_cases: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    case_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    cases_by_script = {row["自动化脚本"]: row for row in case_rows}
    evidence_by_node = {record.get("test.nodeid"): record for record in evidence}
    rows: list[dict[str, Any]] = []
    for case in junit_cases:
        mapping = cases_by_script.get(case["nodeid"], {})
        log_record = evidence_by_node.get(case["nodeid"], {})
        rows.append(
            {
                "case_id": mapping.get("用例编号", log_record.get("test.case_id", "-")),
                "module": mapping.get("模块", "未映射"),
                "scenario": mask_text(mapping.get("场景", case["name"])),
                "priority": mapping.get("优先级", "-"),
                "test_type": mapping.get("测试类型", "接口"),
                "automation_script": case["nodeid"],
                "result": case["result"],
                "duration_ms": round(
                    float(log_record.get("test.duration_ms", case["duration_ms"])), 2
                ),
                "executed_at": log_record.get("timestamp", ""),
                "detail": case["detail"],
            }
        )
    return rows


def parse_coverage() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = read_json(REPORTS / "coverage.json")
    totals = payload["totals"]
    files = []
    for filename, details in payload.get("files", {}).items():
        summary = details.get("summary", {})
        files.append(
            {
                "file": filename.replace("\\", "/"),
                "percent": round(float(summary.get("percent_covered", 0)) / 100, 6),
                "statements": int(summary.get("num_statements", 0)),
                "covered": int(summary.get("covered_lines", 0)),
                "missing": int(summary.get("missing_lines", 0)),
                "branches": int(summary.get("num_branches", 0)),
                "partial_branches": int(summary.get("num_partial_branches", 0)),
            }
        )
    files.sort(key=lambda item: (item["percent"], item["file"]))
    return (
        {
            "percent": round(float(totals.get("percent_covered", 0)) / 100, 6),
            "statements": int(totals.get("num_statements", 0)),
            "covered": int(totals.get("covered_lines", 0)),
            "missing": int(totals.get("missing_lines", 0)),
            "branches": int(totals.get("num_branches", 0)),
            "covered_branches": int(totals.get("covered_branches", 0)),
            "branch_percent": round(
                float(totals.get("percent_branches_covered", 0)) / 100, 6
            ),
        },
        files,
    )


def parse_performance() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    with (REPORTS / "performance" / "locust_stats.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("Name")]
    aggregate = next(row for row in rows if row.get("Name") == "Aggregated")
    endpoints = []
    for row in rows:
        if row.get("Name") == "Aggregated":
            continue
        endpoints.append(
            {
                "method": row.get("Type", ""),
                "endpoint": row.get("Name", ""),
                "requests": int(float(row.get("Request Count", 0))),
                "failures": int(float(row.get("Failure Count", 0))),
                "rps": round(float(row.get("Requests/s", 0)), 3),
                "median_ms": float(row.get("Median Response Time", 0)),
                "average_ms": round(float(row.get("Average Response Time", 0)), 3),
                "p95_ms": float(row.get("95%", 0)),
                "p99_ms": float(row.get("99%", 0)),
                "max_ms": round(float(row.get("100%", 0)), 3),
            }
        )
    endpoints.sort(key=lambda item: item["p95_ms"], reverse=True)
    summary = {
        "requests": int(float(aggregate.get("Request Count", 0))),
        "failures": int(float(aggregate.get("Failure Count", 0))),
        "rps": round(float(aggregate.get("Requests/s", 0)), 3),
        "median_ms": float(aggregate.get("Median Response Time", 0)),
        "average_ms": round(float(aggregate.get("Average Response Time", 0)), 3),
        "p95_ms": float(aggregate.get("95%", 0)),
        "p99_ms": float(aggregate.get("99%", 0)),
        "max_ms": round(float(aggregate.get("100%", 0)), 3),
    }
    run = next(
        record
        for record in reversed(
            read_jsonl(LOGS / "performance" / "performance_run.jsonl")
        )
        if record.get("event") == "performance_run_finished"
    )
    return summary, endpoints, run


def build_log_summary() -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    files = [
        ("logs/access.jsonl", "测试", "访问", "HTTP 请求、状态码、耗时与 request_id"),
        ("logs/app.jsonl", "测试", "应用", "生命周期、业务事件与异常"),
        ("logs/audit.jsonl", "测试", "审计", "登录与订单业务动作"),
        ("logs/security.jsonl", "测试", "安全", "认证失败、权限拒绝与安全事件"),
        ("logs/error.jsonl", "测试", "错误", "ERROR 及以上级别事件"),
        ("logs/tests/test_execution.jsonl", "测试", "执行", "pytest 会话、用例编号、结果与耗时"),
        ("logs/performance/access.jsonl", "性能", "访问", "压测 HTTP 请求与关联字段"),
        ("logs/performance/app.jsonl", "性能", "应用", "压测应用事件与异常"),
        ("logs/performance/audit.jsonl", "性能", "审计", "压测期间业务审计动作"),
        ("logs/performance/security.jsonl", "性能", "安全", "压测期间认证与权限事件"),
        ("logs/performance/error.jsonl", "性能", "错误", "压测期间 ERROR 及以上级别事件"),
        (
            "logs/performance/performance_run.jsonl",
            "性能",
            "编排",
            "压测开始、结束、退出码与聚合指标",
        ),
        (
            "logs/performance/performance_console.log",
            "性能",
            "控制台",
            "Locust 控制台输出留档",
        ),
    ]
    rows = []
    for relative, environment, category, purpose in files:
        path = ROOT / relative
        lines = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        rows.append(
            {
                "file": relative,
                "environment": environment,
                "category": category,
                "records": lines,
                "bytes": path.stat().st_size,
                "purpose": purpose,
                "status": "正常" if (category != "错误" or lines == 0) else "需处理",
            }
        )

    access_records = read_jsonl(LOGS / "performance" / "access.jsonl")
    fields = [
        ("timestamp", "时间戳"),
        ("level", "日志级别"),
        ("logger", "logger"),
        ("service", "服务名"),
        ("environment", "环境"),
        ("request_id", "request_id"),
        ("trace_id", "trace_id"),
        ("event", "事件"),
        ("http.method", "HTTP 方法"),
        ("http.path", "请求路径"),
        ("http.status_code", "状态码"),
        ("http.duration_ms", "耗时"),
        ("http.query", "查询参数"),
        ("http.client_ip", "客户端 IP"),
    ]
    field_rows = []
    for key, label in fields:
        present = sum(
            1
            for record in access_records
            if record.get(key) is not None and record.get(key) != ""
        )
        field_rows.append(
            {
                "field": key,
                "label": label,
                "sample_value": mask_text(access_records[0].get(key, ""))
                if access_records
                else "",
                "coverage": round(present / len(access_records), 6)
                if access_records
                else 0,
            }
        )

    residual_patterns = [
        re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
        re.compile(r"(?:Admin|Operator|Viewer)@123"),
        re.compile(r"local-dev-secret"),
        re.compile(r"(?i)\bBearer\s+(?!\*\*\*)[A-Za-z0-9\-._~+/]{20,}"),
    ]
    residual = 0
    for path in LOGS.rglob("*.jsonl"):
        text = path.read_text(encoding="utf-8", errors="replace")
        residual += sum(len(pattern.findall(text)) for pattern in residual_patterns)
    return rows, field_rows, residual


def build_module_summary(case_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    modules: dict[str, Counter[str]] = {}
    for row in case_rows:
        modules.setdefault(row["模块"], Counter())[row["执行状态"]] += 1
    return [
        {
            "module": module,
            "total": sum(counts.values()),
            "passed": counts.get("通过", 0),
        }
        for module, counts in modules.items()
    ]


def main() -> None:
    summary = read_json(REPORTS / "quality_summary.json")
    case_rows = read_csv(TEST_DESIGN / "test_cases.csv")
    traceability_rows = read_csv(TEST_DESIGN / "traceability_matrix.csv")
    defect_rows = read_csv(DEFECTS / "defect_register.csv")
    risk_rows = read_csv(TEST_DESIGN / "risk_register.csv")
    junit_cases = parse_junit(REPORTS / "test-results.xml")
    evidence, session = latest_session(read_jsonl(LOGS / "tests" / "test_execution.jsonl"))
    execution_rows = build_execution_rows(junit_cases, evidence, case_rows)
    coverage_summary, coverage_files = parse_coverage()
    performance_summary, performance_endpoints, performance_run = parse_performance()
    log_rows, log_fields, residual_secrets = build_log_summary()

    payload = {
        "metadata": {
            "project": summary["project"],
            "version": summary["version"],
            "generated_at": summary["generated_at"],
            "prepared_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "overall_status": summary["overall_status"],
            "release_recommendation": summary["release_recommendation"],
        },
        "test_cases": mask_rows(case_rows),
        "execution_rows": execution_rows,
        "execution_session": session,
        "coverage_summary": coverage_summary,
        "coverage_files": coverage_files,
        "performance_summary": performance_summary,
        "performance_endpoints": performance_endpoints,
        "performance_run": performance_run,
        "defects": mask_rows(defect_rows),
        "risks": mask_rows(risk_rows),
        "traceability": mask_rows(traceability_rows),
        "module_summary": build_module_summary(case_rows),
        "quality_gates": summary["quality_gates"],
        "log_rows": log_rows,
        "log_fields": log_fields,
        "residual_secret_matches": residual_secrets,
        "counts": {
            "case_total": len(case_rows),
            "interface_cases": sum(
                1 for row in case_rows if row["测试类型"] not in {"性能", "稳定性"}
            ),
            "performance_cases": sum(
                1 for row in case_rows if row["测试类型"] in {"性能", "稳定性"}
            ),
            "executed": len(execution_rows),
            "passed": sum(1 for row in execution_rows if row["result"] == "通过"),
            "defects": len(defect_rows),
            "open_defects": sum(
                1
                for row in defect_rows
                if row["状态"] not in {"已关闭", "已接受", "已拒绝"}
            ),
            "risks": len(risk_rows),
            "requirements": len(traceability_rows),
        },
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"workbook data: {OUTPUT}")
    print(
        f"cases={len(case_rows)} executed={len(execution_rows)} "
        f"coverage={coverage_summary['percent']:.2%} "
        f"requests={performance_summary['requests']} "
        f"residual_secrets={residual_secrets}"
    )


if __name__ == "__main__":
    main()
