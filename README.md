# Literature Search Workbench v0.2

A Python + Streamlit research utility built on the existing v0.1 PubMed workbench.
It searches **PubMed** and creates multiple **Covidence-compatible RIS** files plus a CSV and JSON audit log. This is a **research prototype**, not a replacement for Covidence or a comprehensive cross-database search system.

## What changed from v0.1

- **Preview first 100** records for fast smoke tests.
- **Fetch ALL matching PubMed records** across publication years using recursively split, inclusive publication-date windows until each contains ≤9,000 records (below PubMed's 10,000 ESearch cap).
- 200-record EFetch batches; HTTPS retries and NCBI-compatible request throttling.
- SQLite checkpoints **per completed date window**; restart the app, repeat the same query/years, and continue instead of downloading completed windows again.
- Dedupe on PMID and reconcile **(1) count of subwindows, (2) distinct retrieved PMIDs, and (3) initial full-search count** before marking a run complete.
- Export a ZIP containing `.ris` parts sized **≤15,000 citations, ≤49 MB each**, plus `pubmed_records.csv`, `search_audit.json`, and Covidence upload directions. RIS includes available title, ordered authors, journal, year, volume, issue, pages, abstract, DOI, PMID, and URL.

## Windows startup

1. Install **64-bit Python 3.12** if you do not have 3.11/3.12/3.13 64-bit installed. Python 3.14 may cause pandas to build from source, so the Windows script deliberately chooses a compatible version.
2. Unzip the release. Double-click **`一键启动_Windows_v0.2.bat`** inside the project folder.
3. On first Streamlit launch, if a terminal asks `Email:`, **press Enter** to skip.
4. The website should open at **http://127.0.0.1:8501**; keep the command prompt window open.
5. Choose **Preview first 100** to verify the query, then **Fetch ALL matching PubMed records**. For a test use `CORDIOPREV` for 2020–2026 before starting a large search.
6. When marked **COMPLETE**, choose **Prepare Covidence ZIP**, then click the ZIP download button.
7. **Extract** the ZIP; import each numbered `.ris` individually via Covidence Review > **Import Studies** (source `PubMed`, appropriate screening stage). Check import history for deduplication.

Important: With a very broad query like `T2DM` (40,000+ hits), the full download can take **minutes or longer** depending on PubMed and local network conditions. You can interrupt; completed date windows are saved locally.

## Platform-independent startup

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

You can use `Start_Mac_Linux.sh` on Unix. Python 3.11–3.13 64-bit recommended.

## Tests

```bash
python -m pip install pytest
python -m pytest -q
```

Unit/integration-style tests use fake PubMed responses: date splitting, completeness failures, simulated 12,000-record retrieval, checkpoint/resume, XML metadata extraction, RIS formatting, and ZIP splitting. **The tests do not contact PubMed and do not prove a successful live Covidence import**; test a small real import in Covidence before relying on the tool for a review.

## Caveats & research integrity

- **Publication-date disjointness:** PubMed's date indexing can include incomplete publication dates or change during an active search. Some unusual records (such as PubmedBookArticle) may not map to the current citation parser. If windows do not reconcile or an unpartitionable single day exceeds 9,000, the software **stops with an explicit INCOMPLETE warning**. Do not interpret a partial ZIP as a complete search.
- **Live database:** Result sets are *not a transactional snapshot*. Final count equality is a strong programmatic check but cannot prove the database did not change during a run. Document search times, query, and any deviations for systematic reviews.
- This project only searches **PubMed**. Covidence supports RIS imports and performs eligibility screening/deduplication. There is **no direct Covidence API synchronization**.
- Local SQLite checkpoint directory is `.workbench_runs/`, which is excluded from Git. **Streamlit Community Cloud disk is ephemeral and not a safe long-running/resumable job store**; for large jobs, use the local Windows version, or upgrade to a proper background queue with durable cloud storage.
- A public Streamlit deployment has no per-user authentication/isolation in this app. Do not use it for confidential project searches without implementing authentication and separate storage.
- Do **not** commit article abstracts, downloaded CSV/RIS/ZIP data, `.env` secrets, or API keys to a public repo. Some PubMed abstracts have copyright restrictions.

Optional NCBI environment variables: `NCBI_EMAIL`, `NCBI_API_KEY` (not required for moderate use). Respect NCBI usage rules.

## Deploying Streamlit (light usage)

Upload only the source code, `requirements.txt`, `.streamlit/config.toml`, `.gitignore`, tests and documentation to GitHub. Deploy the `main` branch and `app.py` from https://share.streamlit.io/ . For tens of thousands of records, **run the full job locally** due to service timeouts/resource limits and ephemeral storage.

## Documentation

- NCBI E-utilities: https://www.ncbi.nlm.nih.gov/books/NBK25499/
- PubMed date filters: https://pubmed.ncbi.nlm.nih.gov/help/
- Covidence RIS import: https://support.covidence.org/help/study-imports

MIT license applies to source code only, not PubMed/publisher content. No affiliation with or endorsement from NCBI/Covidence.
