from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
V2_DIR = ROOT / "data" / "book_catalog" / "search-text-v2"
API_BASE = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

STAGES = {
    "generation": {
        "batch": V2_DIR / "openai-generation-batch.jsonl",
        "manifest": V2_DIR / "generation-batch-manifest.json",
        "job": V2_DIR / "openai-generation-job.json",
        "output": V2_DIR / "openai-generation-output.jsonl",
        "errors": V2_DIR / "openai-generation-errors.jsonl",
    },
    "verification": {
        "batch": V2_DIR / "openai-verification-batch.jsonl",
        "manifest": V2_DIR / "verification-batch-manifest.json",
        "job": V2_DIR / "openai-verification-job.json",
        "output": V2_DIR / "openai-verification-output.jsonl",
        "errors": V2_DIR / "openai-verification-errors.jsonl",
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def api_key() -> str:
    value = os.environ.get("OPENAI_API_KEY", "").strip()
    if not value:
        raise ValueError(
            "OPENAI_API_KEY is not configured. Set it in the process environment; "
            "do not write it to project files."
        )
    return value


def request(
    method: str,
    endpoint: str,
    *,
    body: bytes | None = None,
    content_type: str = "application/json",
) -> tuple[bytes, dict[str, str]]:
    headers = {"Authorization": f"Bearer {api_key()}"}
    if body is not None:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(API_BASE + endpoint, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return response.read(), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:4000]
        raise RuntimeError(f"OpenAI API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenAI API connection error: {exc.reason}") from exc


def request_json(method: str, endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    raw, _ = request(method, endpoint, body=body)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("OpenAI API returned a non-object response")
    return value


def multipart_file(path: Path) -> tuple[bytes, str]:
    boundary = "----FlowPages" + uuid.uuid4().hex
    content = path.read_bytes()
    chunks = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="purpose"\r\n\r\n',
        b"batch\r\n",
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            "Content-Type: application/jsonl\r\n\r\n"
        ).encode(),
        content,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def submit(args: argparse.Namespace) -> None:
    paths = STAGES[args.stage]
    batch_path: Path = paths["batch"]
    manifest_path: Path = paths["manifest"]
    if not batch_path.exists() or not manifest_path.exists():
        raise FileNotFoundError(f"export {args.stage} batch before submitting it")
    batch_bytes = batch_path.read_bytes()
    if not batch_bytes.strip():
        raise ValueError("batch file is empty")
    if len(batch_bytes) > 200 * 1024 * 1024:
        raise ValueError("batch file exceeds the 200 MB Batch API limit")

    manifest = read_json(manifest_path)
    expected_hash = manifest.get("batchFileSha256")
    actual_hash = sha256_bytes(batch_bytes)
    if expected_hash != actual_hash:
        raise ValueError("batch file hash does not match its manifest; export it again")

    multipart, content_type = multipart_file(batch_path)
    uploaded_raw, _ = request("POST", "/files", body=multipart, content_type=content_type)
    uploaded = json.loads(uploaded_raw.decode("utf-8"))
    file_id = uploaded.get("id")
    if not file_id:
        raise RuntimeError("file upload response has no id")

    batch = request_json("POST", "/batches", {
        "input_file_id": file_id,
        "endpoint": "/v1/responses",
        "completion_window": "24h",
        "metadata": {
            "project": "flowpages-search-text-v2",
            "stage": args.stage,
            "batch_sha256": actual_hash,
        },
    })
    job = {
        "stage": args.stage,
        "submittedAt": now_iso(),
        "batchFile": str(batch_path.relative_to(ROOT)).replace("\\", "/"),
        "batchFileSha256": actual_hash,
        "inputFileId": file_id,
        "batchId": batch.get("id"),
        "status": batch.get("status"),
        "remote": batch,
    }
    write_json(paths["job"], job)
    print(json.dumps({
        "stage": args.stage,
        "batchId": job["batchId"],
        "status": job["status"],
        "jobFile": str(paths["job"].relative_to(ROOT)).replace("\\", "/"),
    }, ensure_ascii=False, indent=2))


def download_file(file_id: str, destination: Path) -> None:
    raw, _ = request("GET", f"/files/{file_id}/content")
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(destination)


def status(args: argparse.Namespace) -> None:
    paths = STAGES[args.stage]
    job_path: Path = paths["job"]
    if not job_path.exists():
        raise FileNotFoundError(f"no submitted {args.stage} job")
    job = read_json(job_path)
    batch_id = str(job.get("batchId", ""))
    if not batch_id:
        raise ValueError("job file has no batchId")
    batch = request_json("GET", f"/batches/{batch_id}")
    job["checkedAt"] = now_iso()
    job["status"] = batch.get("status")
    job["remote"] = batch

    downloads = {}
    if args.download:
        output_file_id = str(batch.get("output_file_id") or "")
        error_file_id = str(batch.get("error_file_id") or "")
        if output_file_id:
            download_file(output_file_id, paths["output"])
            downloads["output"] = str(paths["output"].relative_to(ROOT)).replace("\\", "/")
        if error_file_id:
            download_file(error_file_id, paths["errors"])
            downloads["errors"] = str(paths["errors"].relative_to(ROOT)).replace("\\", "/")
    job["downloads"] = downloads
    write_json(job_path, job)
    print(json.dumps({
        "stage": args.stage,
        "batchId": batch_id,
        "status": batch.get("status"),
        "requestCounts": batch.get("request_counts"),
        "usage": batch.get("usage"),
        "downloads": downloads,
    }, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Submit and retrieve FlowPages OpenAI Batch jobs")
    subparsers = parser.add_subparsers(dest="command", required=True)
    submit_parser = subparsers.add_parser("submit")
    submit_parser.add_argument("stage", choices=sorted(STAGES))
    submit_parser.set_defaults(func=submit)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("stage", choices=sorted(STAGES))
    status_parser.add_argument("--download", action="store_true")
    status_parser.set_defaults(func=status)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
