"""Public PubMed E-utilities client, with polite throttling and batch export.

Only public bibliographic metadata and abstracts are retrieved. This module does
not download copyrighted publisher PDFs or perform automated relevance screening.
"""
from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL_NAME = "literature-search-workbench"


@dataclass(frozen=True)
class SearchInfo:
    count: int
    query: str
    webenv: str
    query_key: str
    searched_at: str


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = "LiteratureSearchWorkbench/0.1 (research metadata tool)"
    return session


def _request(session: requests.Session, endpoint: str, params: dict) -> requests.Response:
    shared = {"tool": TOOL_NAME, **params}
    email = os.getenv("NCBI_EMAIL", "").strip()
    api_key = os.getenv("NCBI_API_KEY", "").strip()
    if email:
        shared["email"] = email
    if api_key:
        shared["api_key"] = api_key
    response = session.get(f"{BASE_URL}/{endpoint}", params=shared, timeout=45)
    response.raise_for_status()
    return response


def search_pubmed(session: requests.Session, query: str, from_year: int, to_year: int) -> SearchInfo:
    if not query or not query.strip():
        raise ValueError("Enter at least one keyword or a PubMed Boolean query.")
    if not (1800 <= from_year <= to_year <= 2100):
        raise ValueError("Invalid year range.")
    # PubMed date-range syntax: YYYY:YYYY[dp]
    full_query = f"({query.strip()}) AND {from_year}:{to_year}[dp]"
    data = _request(session, "esearch.fcgi", {
        "db": "pubmed", "term": full_query, "usehistory": "y",
        "retmax": "0", "retmode": "json", "sort": "pub_date",
    }).json()
    result = data.get("esearchresult", {})
    if "ERROR" in result or "error" in result:
        raise ValueError(result.get("ERROR", result.get("error", "PubMed search failed")))
    count = int(result.get("count", 0))
    return SearchInfo(
        count=count,
        query=result.get("querytranslation", full_query),
        webenv=result.get("webenv", ""),
        query_key=result.get("querykey", ""),
        searched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def _flatten_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def _get_year(article: ET.Element) -> str:
    for path in (
        "./MedlineCitation/Article/ArticleDate/Year",
        "./MedlineCitation/Article/Journal/JournalIssue/PubDate/Year",
        "./MedlineCitation/DateCompleted/Year",
    ):
        value = article.findtext(path)
        if value and value.isdigit():
            return value
    medline_date = article.findtext("./MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate", "")
    match = re.search(r"\b(18|19|20)\d{2}\b", medline_date)
    return match.group(0) if match else ""


def _parse_record(article: ET.Element) -> dict[str, str]:
    citation = article.find("./MedlineCitation")
    details = citation.find("./Article") if citation is not None else None
    if details is None:
        return {}
    pmid = _flatten_text(citation.find("./PMID"))
    if not pmid:
        return {}
    author_list = []
    for author in details.findall("./AuthorList/Author"):
        collective = _flatten_text(author.find("CollectiveName"))
        if collective:
            author_list.append(collective)
            continue
        last = _flatten_text(author.find("LastName"))
        given = _flatten_text(author.find("ForeName")) or _flatten_text(author.find("Initials"))
        author_name = " ".join(filter(None, [given, last]))
        if author_name:
            author_list.append(author_name)

    abstract_segments = []
    for node in details.findall("./Abstract/AbstractText"):
        label = node.get("Label", "")
        value = _flatten_text(node)
        if value:
            abstract_segments.append(f"{label}: {value}" if label else value)
    doi = ""
    for ident in article.findall("./PubmedData/ArticleIdList/ArticleId"):
        if ident.attrib.get("IdType", "").lower() == "doi":
            doi = _flatten_text(ident)
            break
    if not doi:
        for ident in details.findall("./ELocationID"):
            if ident.attrib.get("EIdType", "").lower() == "doi":
                doi = _flatten_text(ident)
                break
    return {
        "Title": _flatten_text(details.find("./ArticleTitle")),
        "Authors": "; ".join(author_list),
        "Year": _get_year(article),
        "Journal": _flatten_text(details.find("./Journal/Title")),
        "Abstract": "\n".join(abstract_segments),
        "DOI": doi,
        "PMID": pmid,
        "PubMed URL": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "Source": "PubMed",
    }


def parse_pubmed_xml(xml_bytes: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(xml_bytes)
    return [item for article in root.findall("./PubmedArticle") if (item := _parse_record(article))]


def fetch_pubmed(
    session: requests.Session,
    search_info: SearchInfo,
    max_records: int,
    update: Callable[[int, int], None] | None = None,
    batch_size: int = 200,
) -> list[dict[str, str]]:
    """Fetch up to 10,000 PubMed results (NCBI ESearch retrieval limit)."""
    if search_info.count == 0:
        return []
    if not search_info.webenv or not search_info.query_key:
        raise ValueError("PubMed did not provide a result history; please search again.")
    total = min(search_info.count, max_records, 10_000)
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for offset in range(0, total, batch_size):
        size = min(batch_size, total - offset)
        # Stay below NCBI's 3 requests/s limit without an API key.
        time.sleep(0.40)
        response = _request(session, "efetch.fcgi", {
            "db": "pubmed", "query_key": search_info.query_key,
            "WebEnv": search_info.webenv, "retstart": str(offset),
            "retmax": str(size), "retmode": "xml",
        })
        for item in parse_pubmed_xml(response.content):
            if item["PMID"] not in seen:
                records.append(item)
                seen.add(item["PMID"])
        if update is not None:
            update(min(offset + size, total), total)
    return records


def to_ris(records: list[dict[str, str]]) -> str:
    """Export a basic RIS bibliography that Zotero and EndNote can import."""
    result = []
    for r in records:
        lines = ["TY  - JOUR"]
        for author in r.get("Authors", "").split("; "):
            if author.strip():
                lines.append(f"AU  - {author}")
        for key, tag in (
            ("Title", "TI"), ("Journal", "JO"), ("Year", "PY"),
            ("Abstract", "AB"), ("DOI", "DO"), ("PubMed URL", "UR"),
            ("PMID", "AN"),
        ):
            value = str(r.get(key, "")).replace("\r", " ").replace("\n", " ").strip()
            if value:
                lines.append(f"{tag}  - {value}")
        result.append("\n".join(lines + ["ER  - ", ""]))
    return "\n".join(result)
