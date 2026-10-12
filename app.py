"""Literature Search Workbench v0.2 — Streamlit PubMed -> Covidence."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from covidence_export import FIELDS, write_covidence_bundle
from pubmed import fetch_preview_pubmed, make_session, search_pubmed, to_ris
from retrieval import IncompleteSearchError, SearchStore, execute_full_search, get_run_id

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / ".workbench_runs"
DATA_FILE = DATA_DIR / "checkpoints.sqlite3"

st.set_page_config(page_title="Literature Search Workbench | v0.2", page_icon="📚", layout="wide")
st.title("📚 Literature Search Workbench")
st.caption("v0.2 · Complete date-partitioned PubMed retrieval · Covidence-ready RIS · Resume support")

with st.expander("ℹ️ Scope, data quality & usage", expanded=False):
    st.markdown("""
    - **PubMed only** (not Scopus, Embase or all literature). A full job automatically partitions
      large results by publication date and attempts to retrieve every PMID in the selected date range.
    - The app **never claims completion** unless date-window counts and distinct PMID totals reconcile.
      Very dense single-day windows, stale PubMed results, some book records and outages will stop the job
      with an explicit incomplete warning. Retry or revise the search.
    - The PubMed index is live; counts may change during long jobs. RIS files contain citations and
      available abstracts, **not PDFs**. Covidence performs screening, not this app.
    - Local job checkpoints are saved to `.workbench_runs/`; **do not upload this folder to GitHub**.
      On Streamlit Community Cloud, local checkpoints can be lost when the app restarts or redeploys.
      Public/shared cloud deployments do not provide separate per-user workspaces or access control.
    """)

with st.form("search_form"):
    query = st.text_area("Keywords / PubMed query", value="T2DM", height=90,
                         help="Examples: T2DM or (adolescent obesity[Title/Abstract]) AND intervention[Title/Abstract]")
    col1, col2 = st.columns(2)
    with col1:
        start_year = st.number_input("Start publication year", min_value=1800,
                                     max_value=date.today().year, value=max(1800, date.today().year - 10), step=1)
    with col2:
        end_year = st.number_input("End publication year", min_value=1800,
                                   max_value=date.today().year, value=date.today().year, step=1)
    mode = st.radio("Retrieval mode", ("Preview first 100", "Fetch ALL matching PubMed records"), index=0,
                    help="Preview makes a quick test; only ALL mode supports certified full Covidence export.")
    fresh = st.checkbox("Start fresh (delete previous checkpoint for the same query + year range)", value=False)
    submitted = st.form_submit_button("🔎 Search PubMed", type="primary", use_container_width=True)

if start_year > end_year:
    st.error("Start year must not exceed end year.")
    st.stop()

run_id = get_run_id(query, int(start_year), int(end_year))

if submitted and not query.strip():
    st.error("Please enter a search query.")
    st.stop()

if submitted:
    if mode == "Preview first 100":
        try:
            session = make_session()
            with st.spinner("Searching PubMed and retrieving a small preview…"):
                info = search_pubmed(session, query, int(start_year), int(end_year))
                records = fetch_preview_pubmed(session, info, 100)
            st.session_state["preview"] = {"spec": run_id, "count": info.count, "data": records,
                                           "translation": info.query, "time": info.searched_at}
        except Exception as err:
            st.error(f"Preview failed: {err}")
    else:
        st.session_state.pop("preview", None)
        try:
            store = SearchStore(DATA_FILE)
            status = st.status("Planning and fetching PubMed windows…", expanded=True)
            progress = st.progress(0.0, text="Starting…")
            log = status.empty()

            def note(message):
                log.write(message)

            def advance(done, total):
                progress.progress(min(1.0, done / total) if total else 1.0,
                                  text=f"Fetched positions: {done:,} / {total:,}  (not yet verified unique)")

            try:
                execute_full_search(make_session(), store, query, int(start_year), int(end_year),
                                    fresh=fresh, on_event=note, on_progress=advance)
                status.update(label="PubMed retrieval complete and counts reconciled", state="complete")
                st.success("Every expected PMID was retrieved and reconciled for the initial search count.")
            finally:
                store.close()
        except IncompleteSearchError as err:
            st.error(f"INCOMPLETE search: {err}")
            st.info("Previously completed date windows remain saved. You may retry with the same settings or start fresh.")
        except (requests.RequestException, ValueError, OSError, json.JSONDecodeError) as err:
            st.error(f"Search stopped: {err}")
            st.info("Network failure or changing database? Run the same query again to resume completed windows.")
        except Exception as err:
            st.error(f"Unexpected error: {err}")

preview = st.session_state.get("preview")
if preview and preview["spec"] == run_id:
    st.subheader("Preview results — NOT the full search")
    a, b = st.columns(2)
    a.metric("PubMed matches", f"{preview['count']:,}")
    b.metric("Preview records", f"{len(preview['data']):,}")
    st.code(preview["translation"], language="text")
    if preview["data"]:
        df = pd.DataFrame(preview["data"])
        st.dataframe(df[["Title", "Authors", "Year", "Journal", "DOI", "PMID"]],
                     hide_index=True, use_container_width=True)
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("⬇ Preview CSV", df[[f for f in FIELDS if f in df]].to_csv(index=False).encode("utf-8-sig"),
                               file_name="SAMPLE_pubmed.csv", mime="text/csv")
        with c2:
            st.download_button("⬇ Preview RIS (sample only)", to_ris(preview["data"]).encode("utf-8"),
                               file_name="SAMPLE_pubmed.ris", mime="application/x-research-info-systems")

if DATA_FILE.exists():
    store = SearchStore(DATA_FILE)
    try:
        run = store.run(run_id)
        if run:
            st.divider()
            st.subheader("Saved full-search job")
            status_complete = run["status"] == "complete" and store.record_count(run_id) == run["expected"]
            wins = store.windows(run_id)
            finished = sum(w["status"] == "done" for w in wins)
            c1, c2, c3 = st.columns(3)
            c1.metric("Initial PubMed matches", f"{run['expected']:,}")
            c2.metric("Unique PMIDs saved", f"{store.record_count(run_id):,}")
            c3.metric("Finished date windows", f"{finished} / {len(wins)}")
            if status_complete:
                st.success("COMPLETE: date-window counts reconcile with the initial PubMed count.")
            else:
                st.warning("INCOMPLETE: saved records are a checkpoint, not all PubMed results. "
                           "Select full retrieval above and click Search to continue.")
            st.caption(f"Initial search (UTC): {run['searched_at']} · Job status: {run['status']}")
            st.code(run["translated"], language="text")
            with st.expander("Date-partition checkpoint details"):
                st.dataframe(pd.DataFrame(wins), use_container_width=True, hide_index=True)
            sample = store.sample(run_id, 200)
            if sample:
                st.subheader("Saved citation preview (first 200 only)")
                df = pd.DataFrame(sample)
                st.dataframe(df[["Title", "Authors", "Year", "Journal", "DOI", "PMID", "PubMed URL"]],
                             use_container_width=True, hide_index=True,
                             column_config={"PubMed URL": st.column_config.LinkColumn("PubMed")})
                with st.expander("Browse a saved abstract"):
                    selection = st.number_input("Preview record number", 1, len(sample), value=1)
                    paper = sample[int(selection) - 1]
                    st.write(f"**{paper['Title']}**")
                    st.write(paper.get("Abstract") or "Abstract not available in PubMed.")

            st.subheader("Covidence import package")
            st.caption("Produces a ZIP of numbered RIS files (≤15,000 citations and <49 MB per RIS), "
                       "CSV and a reproducibility log. Extract ZIP before uploading RIS files one by one.")
            allow_partial = False
            if not status_complete:
                allow_partial = st.checkbox("I understand: allow a clearly marked INCOMPLETE export for debugging",
                                            value=False)
            if st.button("📦 Prepare Covidence ZIP", disabled=not (status_complete or allow_partial)):
                try:
                    filename = f"covidence_{run_id}_{run['searched_at'].replace(':','-')}.zip"
                    out = DATA_DIR / filename
                    with st.spinner("Building numbered RIS batches and audit log…"):
                        audit = write_covidence_bundle(store, run_id, out, allow_incomplete=allow_partial)
                    st.success(f"Prepared {len(audit['ris_parts'])} RIS files; "
                               f"{audit['unique_records_exported']:,} records.")
                except Exception as err:
                    st.error(f"Covidence export failed: {err}")
            filename = f"covidence_{run_id}_{run['searched_at'].replace(':','-')}.zip"
            output = DATA_DIR / filename
            if output.is_file() and (status_complete or allow_partial):
                with open(output, "rb") as input_zip:
                    st.download_button("⬇ Download Covidence RIS + CSV + audit ZIP", input_zip,
                                       file_name=output.name, mime="application/zip", use_container_width=True)
    finally:
        store.close()

st.divider()
st.caption("Uses NCBI E-utilities; not endorsed by NCBI or Covidence. Search export does not perform eligibility screening. "
           "Do not publish downloaded bibliographic abstracts or private research records in public GitHub repositories.")
