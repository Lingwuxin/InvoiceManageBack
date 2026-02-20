import argparse
import json
import sys
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def http_request(method: str, url: str, token: str, payload: dict | None = None) -> tuple[int, bytes, dict]:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return resp.status, resp.read(), dict(resp.headers)


def extract_docx_text(docx_bytes: bytes) -> str:
    with zipfile.ZipFile(Path("_temp.docx"), "w") as temp:
        temp.writestr("word/document.xml", docx_bytes)

    with zipfile.ZipFile(Path("_temp.docx"), "r") as zf:
        doc_xml = zf.read("word/document.xml")

    root = ET.fromstring(doc_xml)
    texts = []
    for node in root.findall(".//w:t", NS):
        if node.text:
            texts.append(node.text)
    return "".join(texts)


def compute_travel_range(payload: dict) -> str:
    start = payload.get("departure_date")
    end = payload.get("return_date")
    if start and end:
        return f"{start}至{end}"
    return ""


def add_expected(expectations: list[tuple[str, str]], label: str, value: object) -> None:
    if value is None:
        return
    text = str(value).strip()
    if text:
        expectations.append((label, text))


def check_item_keys(items: list[dict], expected_keys: set[str], label: str) -> list[str]:
    warnings = []
    for idx, item in enumerate(items, 1):
        missing = sorted(k for k in expected_keys if k not in item)
        if missing:
            warnings.append(f"{label}[{idx}] missing keys: {', '.join(missing)}")
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Check reimbursement export docx content.")
    parser.add_argument("--base-url", default="http://localhost:8000/api", help="API base URL")
    parser.add_argument("--token", required=True, help="JWT access token")
    parser.add_argument("--payload", required=True, help="Path to reimbursement payload JSON")
    parser.add_argument("--output", default="reimbursement-export.docx", help="Exported docx path")
    args = parser.parse_args()

    payload_path = Path(args.payload)
    if not payload_path.exists():
        print("payload file not found", file=sys.stderr)
        return 1

    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    status, body, _ = http_request("POST", f"{args.base_url}/reimbursements/", args.token, payload)
    if status not in (200, 201):
        print("create failed", body.decode("utf-8", errors="ignore"), file=sys.stderr)
        return 1

    reimbursement = json.loads(body.decode("utf-8"))
    reimbursement_id = reimbursement.get("id")
    if not reimbursement_id:
        print("missing reimbursement id", file=sys.stderr)
        return 1

    status, export_body, headers = http_request(
        "POST",
        f"{args.base_url}/reimbursements/{reimbursement_id}/export/",
        args.token,
        {},
    )
    if status != 200:
        print("export failed", export_body.decode("utf-8", errors="ignore"), file=sys.stderr)
        return 1

    output_path = Path(args.output)
    output_path.write_bytes(export_body)

    doc_text = extract_docx_text(export_body)

    expectations: list[tuple[str, str]] = []
    add_expected(expectations, "dept", payload.get("dept"))
    add_expected(expectations, "traveler", payload.get("traveler"))
    add_expected(expectations, "project_code", payload.get("project_code"))
    add_expected(expectations, "project_name", payload.get("project_name"))
    add_expected(expectations, "destination", payload.get("departure_place"))
    add_expected(expectations, "purpose", payload.get("purpose"))
    add_expected(expectations, "cost_dept", payload.get("dept"))

    travel_range = payload.get("travel_range") or compute_travel_range(payload)
    add_expected(expectations, "travel_range", travel_range)

    for item in payload.get("transport_items", []):
        add_expected(expectations, "transport departure", item.get("departure_date"))
        add_expected(expectations, "transport from", item.get("departure_place"))
        add_expected(expectations, "transport to", item.get("arrival_place"))
        add_expected(expectations, "transport amount", item.get("amount"))

    for item in payload.get("accommodation_items", []):
        add_expected(expectations, "accommodation amount", item.get("actual_cost"))

    for item in payload.get("expense_items", []):
        add_expected(expectations, "expense amount", item.get("amount"))

    missing = [label for label, value in expectations if value not in doc_text]

    if missing:
        print("missing fields in export:")
        for label in missing:
            print(f"- {label}")
    else:
        print("all expected fields found")

    warnings = []
    warnings.extend(check_item_keys(payload.get("transport_items", []), {
        "departure_date",
        "departure_place",
        "arrival_date",
        "arrival_place",
        "transport_type",
        "quantity",
        "amount",
    }, "transport_items"))
    warnings.extend(check_item_keys(payload.get("accommodation_items", []), {
        "city",
        "num_nights",
        "standard_cost",
        "actual_cost",
        "amount",
    }, "accommodation_items"))
    warnings.extend(check_item_keys(payload.get("expense_items", []), {
        "expense_type",
        "expense_name",
        "quantity",
        "amount",
        "remark",
    }, "expense_items"))

    if warnings:
        print("payload/schema warnings:")
        for warning in warnings:
            print(f"- {warning}")

    print(f"export saved to {output_path}")
    print(f"Content-Type: {headers.get('Content-Type', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
