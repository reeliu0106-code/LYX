# Literature Search Workbench (PubMed MVP)

A small, open-source Streamlit application for **reproducible literature searches on PubMed**. Search a PubMed Boolean expression, retrieve bibliographic metadata and available abstracts, review records, and export CSV, RIS (for Zotero/EndNote), and a JSON search log.

> **Scope:** This searches only PubMed; it does not search every academic database or perform eligibility screening. PubMed ESearch is limited to the first **10,000** matching records per query. For large searches, split searches into smaller publication-year ranges and combine/de-duplicate exports. Retrieving article metadata is not the same as obtaining publisher PDFs.

## Run locally

1. Install Python 3.11 or 3.12.
2. Open a terminal in the project folder.
3. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

4. Start the web interface:

   ```bash
   python -m streamlit run app.py
   ```

5. Your browser should open at `http://localhost:8501`.

Optional: Configure `NCBI_EMAIL` (your contact email) and `NCBI_API_KEY` as **environment variables**. Never commit an API key to GitHub. A key is not required for ordinary, low-rate usage. The application throttles EFetch requests to below three per second.

## Usage

1. Enter keywords or an advanced PubMed expression, such as `("adolescent obesity"[Title/Abstract]) AND intervention[Title/Abstract]`.
2. Choose publication years and maximum result count, then click **Search PubMed**.
3. Check PubMed matches vs. downloaded records; choose 10,000 if all matches fit within that limit.
4. Download `pubmed_results.csv`, `pubmed_results.ris` (Zotero/EndNote), and `search_log.json` (database, query translation, date, result count).

Some PubMed records have no abstract or DOI. Those fields may be empty.

## Publish to GitHub + deploy

1. Create a **new GitHub repository** (e.g. `literature-search-workbench`).
2. Upload the **contents of this folder** to it (not only the ZIP file): `app.py`, `pubmed.py`, `requirements.txt`, `README.md`, `LICENSE`, `.gitignore`, `.streamlit/`, and `tests/`.
3. Go to [Streamlit Community Cloud](https://share.streamlit.io/) and sign in using GitHub.
4. Click **Create app** → select your repository, `main` branch, and `app.py` entrypoint → Deploy.
5. Share both your GitHub source-code URL and the `*.streamlit.app` URL.

A GitHub repository hosts your **source code**; deploying to Streamlit Community Cloud gives your collaborator a **browser-based tool**. Python must be run locally to use the un-deployed app.

## Developer test

```bash
python -m pip install pytest
python -m pytest -q
```

The tests exercise parser and export functions using sample XML. Live PubMed retrieval requires network connectivity and is not covered by unit tests.

## Next steps

- Add Europe PMC, OpenAlex, Crossref, or other API-based coverage (each has different search semantics).
- Deduplicate results by PMID, normalized DOI, and title; preserve source provenance.
- Implement search-history persistence, team tags and manual include/exclude screening.
- Add date-sliced searches for PubMed queries exceeding 10,000 records.
- Add Zotero synchronization if the team requires it, with explicit authorization.

## Data and copyright

Powered by the [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/). NCBI does not endorse this app. PubMed abstracts may be copyrighted and must be handled in accordance with applicable rights and the [NCBI disclaimer](https://www.ncbi.nlm.nih.gov/About/disclaimer.html). Do not publish exported article abstracts to the project's GitHub repository.

MIT license applies only to the source code, not third-party literature content.
