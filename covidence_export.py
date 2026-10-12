"""Covidence-compatible RIS + audit metadata, packed into a single ZIP.

Covidence accepts RIS files. Each .ris is capped at 15,000 references and at
most 49 MB, below Covidence's 50 MB guidance.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from pathlib import Path

MAX_RIS_REFERENCES = 15_000
MAX_RIS_BYTES = 49_000_000
FIELDS = ("PMID", "RIS Type", "Title", "Authors", "Year", "Journal", "Journal Abbrev", "Volume",
          "Issue", "Start Page", "End Page", "ISSN", "DOI", "Abstract", "PubMed URL", "Source")


def _value(v):
    return " ".join(str(v or "").replace("\r", " ").replace("\n", " ").split()).strip()


def ris_entry(record: dict) -> bytes:
    """One properly terminated UTF-8 RIS citation; no abstract truncation."""
    if not _value(record.get("PMID")) or not _value(record.get("Title")):
        raise ValueError("RIS record needs both PMID and Title; cannot export an incomplete citation.")
    ris_type = str(record.get("RIS Type", "JOUR"))
    if ris_type not in ("JOUR", "BOOK", "CHAP"):
        ris_type = "JOUR"
    lines = [f"TY  - {ris_type}"]
    ris_authors = record.get("RIS Authors", [])
    if isinstance(ris_authors, str):
        ris_authors = [part.strip() for part in ris_authors.split(";") if part.strip()]
    if not ris_authors:
        ris_authors = [x.strip() for x in str(record.get("Authors", "")).split("; ") if x.strip()]
    for name in ris_authors:
        if _value(name):
            lines.append("AU  - " + _value(name))
    mapping = (
        ("Title", "TI"), ("Journal", "JO" if ris_type == "JOUR" else "T2"), ("Journal Abbrev", "JA"),
        ("Year", "PY"), ("Volume", "VL"), ("Issue", "IS"),
        ("Start Page", "SP"), ("End Page", "EP"), ("ISSN", "SN"),
        ("DOI", "DO"), ("Abstract", "AB"), ("PubMed URL", "UR"),
        ("PMID", "AN"), ("Source", "DB"),
    )
    for key, tag in mapping:
        val = _value(record.get(key))
        if val:
            lines.append(f"{tag}  - {val}")
    lines.extend(["ER  - ", ""])
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def write_covidence_bundle(store, run_id: str, out_path: Path | str,
                           *, max_references: int = MAX_RIS_REFERENCES,
                           max_bytes: int = MAX_RIS_BYTES,
                           allow_incomplete: bool = False) -> dict:
    """Create a single ZIP containing numbered RIS imports, CSV and JSON audit log."""
    run = store.run(run_id)
    if not run:
        raise ValueError("Run does not exist.")
    complete = run["status"] == "complete" and store.record_count(run_id) == run["expected"]
    if not complete and not allow_incomplete:
        raise ValueError("Search not certified complete. Resume retrieval before exporting.")
    if not 1 <= max_references <= MAX_RIS_REFERENCES:
        raise ValueError("Each RIS file must contain <=15,000 citations.")
    if not 512 <= max_bytes <= MAX_RIS_BYTES:
        raise ValueError("RIS files must be below 49 MB; this guards Covidence upload size.")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    parts = []
    chunks = []
    idx, count = 1, 0
    ris_buffer = io.BytesIO()
    incomplete_prefix = "INCOMPLETE_" if not complete else ""

    def flush(zipf):
        nonlocal idx, count, ris_buffer
        if not count:
            return
        body = ris_buffer.getvalue()
        name = f"{incomplete_prefix}covidence_pubmed_part_{idx:03d}.ris"
        zipf.writestr(name, body)
        parts.append({"filename": name, "records": count, "bytes": len(body),
                      "sha256": hashlib.sha256(body).hexdigest()})
        idx += 1
        count = 0
        ris_buffer = io.BytesIO()

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as z:
        # Produce CSV without buffering the whole data set. UTF-8 BOM for Excel.
        with z.open("pubmed_records.csv", "w", force_zip64=True) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="", write_through=True)
            writer = csv.DictWriter(text, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            for rec in store.iter_records(run_id):
                writer.writerow({key: rec.get(key, "") for key in FIELDS})
            text.flush()
            text.detach()
        for record in store.iter_records(run_id):
            entry = ris_entry(record)
            if len(entry) > max_bytes:
                raise ValueError(f"Single RIS record ({record.get('PMID')}) exceeds file limit.")
            if count and (count >= max_references or ris_buffer.tell() + len(entry) > max_bytes):
                flush(z)
            ris_buffer.write(entry)
            count += 1
        flush(z)
        audit = {
            "tool": "Literature Search Workbench", "version": "0.2.0",
            "database": "PubMed", "search_query": run["query"],
            "translated_query": run["translated"], "publication_years": [run["first_year"], run["last_year"]],
            "initial_search_utc": run["searched_at"], "latest_checkpoint_utc": run["updated"],
            "expected_matches_at_initial_search": run["expected"],
            "unique_records_exported": store.record_count(run_id),
            "certified_complete_at_initial_count": complete,
            "warning": ("PubMed is a live database: snapshot consistency across a long search cannot be fully guaranteed. "
                        "This completion check compares count/PMIDs across date windows; verify your systematic review strategy."
                        if complete else "PARTIAL RESULTS: not the full PubMed result set."),
            "date_windows": store.windows(run_id),
            "ris_parts": parts,
            "instructions": "Unzip and import each .ris file separately into Covidence Import Studies; choose PubMed source.",
        }
        z.writestr("search_audit.json", json.dumps(audit, ensure_ascii=False, indent=2))
        z.writestr("如何导入Covidence.txt", (
            "Covidence 导入说明\n"
            "1. 解压 ZIP。\n2. 打开 Covidence Review > Import Studies。\n"
            "3. 选择 PubMed 来源、标题/摘要筛选阶段。\n"
            "4. 按编号逐个导入 covidence_pubmed_part_XXX.ris。\n"
            "5. 对照 search_audit.json 检查数量与去重报告。\n"
            "注意：本软件只完成元数据检索，不自动判断研究是否纳入；\n"
            "数据库持续更新，计数校验不能替代正式的检索可复现性审查。\n"
        ).encode("utf-8"))
    return audit
