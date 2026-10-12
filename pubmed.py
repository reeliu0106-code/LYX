"""NCBI PubMed E-utilities client; respectful rate limiting and XML parsing."""
from __future__ import annotations

import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timezone
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
    retries = Retry(total=4, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
                    allowed_methods=("GET",), respect_retry_after_header=True)
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.headers["User-Agent"] = "LiteratureSearchWorkbench/0.2 (PubMed citation research)"
    return session


def _request(session: requests.Session, endpoint: str, params: dict) -> requests.Response:
    # NCBI recommendation: <=3 requests/s without a key, <=10 with a key.
    minimum_gap = 0.38 if not os.getenv("NCBI_API_KEY", "").strip() else 0.11
    last = getattr(session, "_lsw_request_at", None)
    if last is not None:
        time.sleep(max(0.0, minimum_gap - (time.monotonic() - last)))
    session._lsw_request_at = time.monotonic()
    shared = {"tool": TOOL_NAME, **params}
    if os.getenv("NCBI_EMAIL", "").strip():
        shared["email"] = os.environ["NCBI_EMAIL"].strip()
    if os.getenv("NCBI_API_KEY", "").strip():
        shared["api_key"] = os.environ["NCBI_API_KEY"].strip()
    response = session.get(f"{BASE_URL}/{endpoint}", params=shared, timeout=(10, 90))
    response.raise_for_status()
    return response


def _search(session: requests.Session, query: str, *, start: date, end: date) -> SearchInfo:
    if not query.strip():
        raise ValueError("Please enter a PubMed keyword or Boolean expression.")
    if start > end:
        raise ValueError("Start date must not be after end date.")
    response = _request(session, "esearch.fcgi", {
        "db": "pubmed", "term": query.strip(), "usehistory": "y", "retmax": "0",
        "retmode": "json", "sort": "pub_date", "datetype": "pdat",
        "mindate": start.strftime("%Y/%m/%d"), "maxdate": end.strftime("%Y/%m/%d"),
    })
    data = response.json().get("esearchresult", {})
    if "ERROR" in data or "error" in data:
        raise ValueError(data.get("ERROR", data.get("error")))
    if "count" not in data:
        raise ValueError("PubMed returned an unexpected ESearch result.")
    return SearchInfo(count=int(data["count"]), query=str(data.get("querytranslation", query)),
                      webenv=str(data.get("webenv", "")), query_key=str(data.get("querykey", "")),
                      searched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def search_window(session: requests.Session, query: str, start: date, end: date) -> SearchInfo:
    """Publication-date search. Inclusive, contiguous splits cover the same date span."""
    return _search(session, query, start=start, end=end)


def search_pubmed(session: requests.Session, query: str, from_year: int, to_year: int) -> SearchInfo:
    """Backwards-compatible entry point from v0.1."""
    if not 1800 <= from_year <= to_year <= 2100:
        raise ValueError("Invalid publication-year range.")
    return search_window(session, query, date(from_year, 1, 1), date(to_year, 12, 31))


def _flat(element: ET.Element | None) -> str:
    return " ".join("".join(element.itertext()).split()) if element is not None else ""


def _get_year(article: ET.Element) -> str:
    for path in ("./MedlineCitation/Article/ArticleDate/Year",
                 "./MedlineCitation/Article/Journal/JournalIssue/PubDate/Year",
                 "./MedlineCitation/DateCompleted/Year"):
        value = article.findtext(path)
        if value and value.isdigit():
            return value
    medline_date = article.findtext("./MedlineCitation/Article/Journal/JournalIssue/PubDate/MedlineDate", "")
    match = re.search(r"\b(18|19|20)\d{2}\b", medline_date)
    return match.group(0) if match else ""


def _parse_record(article: ET.Element) -> dict[str, str]:
    citation = article.find("./MedlineCitation")
    details = citation.find("./Article") if citation is not None else None
    if details is None or citation is None:
        return {}
    pmid = _flat(citation.find("./PMID"))
    if not pmid:
        return {}

    display_authors, ris_authors = [], []
    for author in details.findall("./AuthorList/Author"):
        collective = _flat(author.find("CollectiveName"))
        if collective:
            display_authors.append(collective)
            ris_authors.append(collective)
            continue
        last = _flat(author.find("LastName"))
        first = _flat(author.find("ForeName")) or _flat(author.find("Initials"))
        suffix = _flat(author.find("Suffix"))
        if last or first:
            display_authors.append(" ".join(x for x in (first, last, suffix) if x))
            ris_authors.append(", ".join(x for x in (last, " ".join(y for y in (first, suffix) if y)) if x))

    abstracts = []
    for node in details.findall("./Abstract/AbstractText"):
        label, value = node.get("Label", ""), _flat(node)
        if value:
            abstracts.append(f"{label}: {value}" if label else value)
    doi = ""
    for ident in article.findall("./PubmedData/ArticleIdList/ArticleId"):
        if ident.attrib.get("IdType", "").lower() == "doi":
            doi = _flat(ident)
            break
    if not doi:
        for ident in details.findall("./ELocationID"):
            if ident.attrib.get("EIdType", "").lower() == "doi":
                doi = _flat(ident)
                break

    pages = _flat(details.find("./Pagination/MedlinePgn")) or _flat(details.find("./Pagination/StartPage"))
    start_page, end_page = (pages.split("-", 1) + [""])[:2] if "-" in pages else (pages, "")
    if not end_page:
        end_page = _flat(details.find("./Pagination/EndPage"))
    journal = details.find("./Journal")
    return {
        "Title": _flat(details.find("./ArticleTitle")),
        "Authors": "; ".join(display_authors),
        "RIS Authors": ris_authors,  # proper Family, Given names, unlike display format
        "Year": _get_year(article),
        "Journal": _flat(journal.find("./Title")) if journal is not None else "",
        "Journal Abbrev": _flat(journal.find("./ISOAbbreviation")) if journal is not None else "",
        "Volume": _flat(journal.find("./JournalIssue/Volume")) if journal is not None else "",
        "Issue": _flat(journal.find("./JournalIssue/Issue")) if journal is not None else "",
        "Start Page": start_page,
        "End Page": end_page,
        "ISSN": _flat(journal.find("./ISSN")) if journal is not None else "",
        "Abstract": "\n".join(abstracts),
        "DOI": doi,
        "PMID": pmid,
        "PubMed URL": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "Source": "PubMed",
    }


def _parse_book_record(article: ET.Element) -> dict[str, str]:
    """Parse the PubmedBookArticle variant used for NCBI Bookshelf items."""
    doc = article.find("./BookDocument")
    if doc is None:
        return {}
    pmid = _flat(doc.find("./PMID"))
    book = doc.find("./Book")
    if not pmid or book is None:
        return {}
    title = _flat(doc.find("./ArticleTitle")) or _flat(book.find("./BookTitle"))
    if not title:
        return {}
    title_of_book = _flat(book.find("./BookTitle"))
    year = (_flat(doc.find("./PubDate/Year")) or
            _flat(book.find("./PubDate/Year")) or
            _flat(book.find("./PubDate/MedlineDate"))[:4])
    authors, ris_authors = [], []
    for author in doc.findall("./AuthorList/Author") or book.findall("./AuthorList/Author"):
        group = _flat(author.find("CollectiveName"))
        last = _flat(author.find("LastName"))
        first = _flat(author.find("ForeName")) or _flat(author.find("Initials"))
        if group:
            authors.append(group)
            ris_authors.append(group)
        elif last or first:
            authors.append(" ".join(x for x in (first, last) if x))
            ris_authors.append(", ".join(x for x in (last, first) if x))
    doi = ""
    for ident in doc.findall("./ArticleIdList/ArticleId"):
        if ident.get("IdType", "").lower() == "doi":
            doi = _flat(ident)
            break
    abstracts = [_flat(n) for n in doc.findall("./Abstract/AbstractText") if _flat(n)]
    return {
        "PMID": pmid, "Title": title, "Authors": "; ".join(authors),
        "RIS Authors": ris_authors, "Year": year, "Journal": title_of_book,
        "Journal Abbrev": "", "Volume": "", "Issue": "", "Start Page": "",
        "End Page": "", "ISSN": "", "Abstract": " ".join(abstracts), "DOI": doi,
        "PubMed URL": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "Source": "PubMed", "RIS Type": "CHAP" if title != title_of_book else "BOOK",
    }


def parse_pubmed_xml(xml_bytes: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(xml_bytes)
    if root.tag != "PubmedArticleSet":
        raise ValueError(f"Unexpected EFetch XML root: {root.tag}")
    records = []
    for node in root:
        if node.tag == "PubmedArticle":
            row = _parse_record(node)
        elif node.tag == "PubmedBookArticle":
            row = _parse_book_record(node)
        else:
            raise ValueError(f"Unsupported EFetch record type: {node.tag}")
        if not row:
            raise ValueError(f"Incomplete {node.tag} (PMID/title metadata missing): batch not marked complete.")
        records.append(row)
    return records


def iter_pubmed_batches(session: requests.Session, info: SearchInfo, batch_size: int = 200):
    """Yield (records, fetched_position, expected_total) without silently truncating."""
    if not 1 <= batch_size <= 1000:
        raise ValueError("Batch size must be between 1 and 1000.")
    if info.count > 10000:
        raise ValueError("A window exceeds 10,000 results; split before EFetch.")
    if info.count and (not info.webenv or not info.query_key):
        raise ValueError("Missing PubMed History token; retry the search.")
    for offset in range(0, info.count, batch_size):
        count = min(batch_size, info.count - offset)
        response = _request(session, "efetch.fcgi", {
            "db": "pubmed", "query_key": info.query_key, "WebEnv": info.webenv,
            "retstart": str(offset), "retmax": str(count), "retmode": "xml",
        })
        items = parse_pubmed_xml(response.content)
        if len(items) != count:
            raise ValueError(f"PubMed batch {offset}-{offset+count} returned {len(items)} records, expected {count}; not complete.")
        yield items, offset + count, info.count


def fetch_pubmed(session: requests.Session, search_info: SearchInfo,
                 max_records: int, update: Callable[[int, int], None] | None = None,
                 batch_size: int = 200) -> list[dict[str, str]]:
    """Legacy API: explicit small limited downloads, for backwards compatibility."""
    if search_info.count > 10000:
        raise ValueError("Use a segmented full retrieval for searches over 10,000 hits.")
    if max_records <= 0:
        return []
    records = []
    for items, position, total in iter_pubmed_batches(session, search_info, batch_size=batch_size):
        records.extend(items[:max(0, max_records - len(records))])
        if update:
            update(min(position, max_records), min(total, max_records))
        if len(records) >= max_records:
            break
    return records


def to_ris(records: list[dict]) -> str:
    """Keep the original v0.1 export function name for existing integrations."""
    from covidence_export import ris_entry
    return "".join(ris_entry(r).decode("utf-8") for r in records)


def fetch_preview_pubmed(session: requests.Session, info: SearchInfo, maximum: int = 100) -> list[dict]:
    """Fetch the first N of any search, explicitly marked a SAMPLE (not all hits)."""
    if not 1 <= maximum <= 1000:
        raise ValueError("Preview size must be between 1 and 1000.")
    total = min(maximum, info.count)
    if not total:
        return []
    if not info.webenv or not info.query_key:
        raise ValueError("PubMed did not return a search history token.")
    records = []
    for offset in range(0, total, 200):
        batch_size = min(total - offset, 200)
        response = _request(session, "efetch.fcgi", {
            "db": "pubmed", "query_key": info.query_key, "WebEnv": info.webenv,
            "retstart": str(offset), "retmax": str(batch_size), "retmode": "xml",
        })
        rows = parse_pubmed_xml(response.content)
        if len(rows) != batch_size:
            raise ValueError("PubMed did not return all requested preview records.")
        records.extend(rows)
    return records
