# v0.2 test report

Environment: Python 3.13, Linux build environment (not Windows).

`python -m pytest -q` -> **23 passed** (offline tests)

Coverage includes: existing v0.1 XML metadata and RIS tests; publication-date split coverage; >10,000 simulated matches; a 12,000-record two-window download; checkpoint and resume following simulated interrupted download; changed match-count detection; duplicate PMID failure; RIS metadata and UTF-8; RIS split by record count / bytes; ZIP CSV and JSON audit; PubmedBookArticle parsing; mocked NCBI API request arguments and preview mode.

`python -m compileall -q app.py pubmed.py retrieval.py covidence_export.py` -> success.

Not verified here: actual Windows batch-script execution; remote NCBI request against live PubMed; true 40,000+ records end-to-end download; import of generated RIS into a Covidence account; Streamlit Community Cloud deployment. The environment does not have Streamlit installed, so the web UI itself has not been launched here. Please perform a small live test before relying on the tool for a formal review.
