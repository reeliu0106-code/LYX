"""Streamlit interface for a reproducible PubMed literature search."""
from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

from pubmed import fetch_pubmed, make_session, search_pubmed, to_ris

st.set_page_config(
    page_title="Literature Search Workbench",
    page_icon="📚", layout="wide"
)
st.title("📚 Literature Search Workbench")
st.caption("PubMed literature discovery, metadata export & reproducible searches | v0.1")

with st.expander("ℹ️ What this tool does (and does not do)", expanded=False):
    st.write(
        "Searches PubMed for bibliographic records; retrieves available abstracts and IDs. "
        "Results are not automatically screened for eligibility. It does not search all academic "
        "databases or download publisher PDFs. PubMed ESearch is limited to the first 10,000 "
        "records per query; split larger queries by year for systematic searches."
    )

with st.form("pubmed_search_form"):
    query = st.text_area(
        "Keywords / PubMed query",
        value='("adolescent obesity"[Title/Abstract]) AND (intervention[Title/Abstract] OR prevention[Title/Abstract])',
        height=100,
        help="Accepts PubMed Boolean operators (AND / OR / NOT) and field tags such as [Title/Abstract].",
    )
    left, right = st.columns(2)
    this_year = datetime.now().year
    with left:
        from_year = st.number_input("Start publication year", min_value=1800, max_value=this_year, value=max(1800, this_year - 10), step=1)
    with right:
        to_year = st.number_input("End publication year", min_value=1800, max_value=this_year, value=this_year, step=1)
    max_records = st.selectbox(
        "Maximum records to download",
        options=[100, 500, 1000, 2500, 5000, 10000], index=1,
        help="Choose 10,000 to retrieve all available matching PubMed records when the match count is ≤10,000.",
    )
    submitted = st.form_submit_button("🔎 Search PubMed", type="primary", use_container_width=True)

if submitted:
    if from_year > to_year:
        st.error("The starting year must be ≤ the ending year.")
    else:
        try:
            session = make_session()
            with st.spinner("Searching PubMed…"):
                info = search_pubmed(session, query, int(from_year), int(to_year))
            if info.count == 0:
                st.session_state.pop("search_result", None)
                st.info("PubMed found no results for this query and date range.")
            else:
                progress = st.progress(0.0, text="Fetching PubMed records…")
                records = fetch_pubmed(
                    session, info, max_records=max_records,
                    update=lambda done, total: progress.progress(
                        min(done / total, 1.0),
                        text=f"Retrieving records: {done:,} / {total:,}"
                    ),
                )
                progress.empty()
                st.session_state["search_result"] = {"records": records, "info": info}
        except (requests.RequestException, ValueError, json.JSONDecodeError) as error:
            st.error(f"Search failed: {error}")
            st.caption("Check your internet connection, PubMed query syntax, or try again later.")
        except Exception as error:
            st.error(f"Unexpected response from PubMed: {error}")

if "search_result" in st.session_state:
    results = st.session_state["search_result"]
    info = results["info"]
    data = results["records"]
    df = pd.DataFrame.from_records(data)
    st.divider()
    first, second, third = st.columns(3)
    first.metric("PubMed matches", f"{info.count:,}")
    second.metric("Downloaded records", f"{len(df):,}")
    third.metric("Missing abstracts", f"{sum(not r['Abstract'] for r in data):,}")

    if info.count > 10_000:
        st.warning(
            "This query matches more than 10,000 PubMed records. "
            "The PubMed ESearch API cannot retrieve beyond the first 10,000 in a single query. "
            "Split the search by narrower year ranges to cover the full period."
        )
    elif len(df) < info.count:
        st.info(
            f"A download limit was selected: {len(df):,} of {info.count:,} matches retrieved. "
            "Choose a higher Maximum records value and search again if needed."
        )
    st.subheader("Search reproducibility")
    st.code(info.query, language="text")
    st.caption(f"Database: PubMed | Search date (UTC): {info.searched_at}")

    if not df.empty:
        st.subheader("Results")
        display = df[["Title", "Authors", "Year", "Journal", "DOI", "PMID", "PubMed URL"]]
        st.dataframe(
            display,
            use_container_width=True,
            hide_index=True,
            column_config={"PubMed URL": st.column_config.LinkColumn("PubMed link")},
        )
        with st.expander("Browse abstracts"):
            view_index = st.number_input(
                "Record number", min_value=1, max_value=len(df), value=1
            )
            paper = data[int(view_index) - 1]
            st.markdown(f"**{paper['Title']}**")
            st.caption(f"{paper['Authors']} · {paper['Year']} · {paper['Journal']}")
            st.write(paper["Abstract"] or "No abstract is available in PubMed.")
            st.markdown(f"[View on PubMed]({paper['PubMed URL']})")

        export_info = {
            "database": "PubMed",
            "query_translation": info.query,
            "search_timestamp_utc": info.searched_at,
            "total_hits": info.count,
            "exported_records": len(data),
            "is_full_result_export": len(data) == info.count,
            "note": "PubMed search results only. Eligibility screening not performed.",
        }
        a, b, c = st.columns(3)
        with a:
            st.download_button(
                "⬇ Download CSV (Excel)",
                data=df.to_csv(index=False).encode("utf-8-sig"),
                file_name="pubmed_results.csv", mime="text/csv",
                use_container_width=True,
            )
        with b:
            st.download_button(
                "⬇ Download RIS (Zotero)",
                data=to_ris(data).encode("utf-8"),
                file_name="pubmed_results.ris", mime="application/x-research-info-systems",
                use_container_width=True,
            )
        with c:
            st.download_button(
                "⬇ Download search log",
                data=json.dumps(export_info, indent=2, ensure_ascii=False).encode("utf-8"),
                file_name="search_log.json", mime="application/json",
                use_container_width=True,
            )

st.divider()
st.caption(
    "Uses NCBI E-utilities. NCBI does not endorse this application. "
    "PubMed abstracts may be copyrighted; respect publisher and NCBI terms. "
    "See https://www.ncbi.nlm.nih.gov/About/disclaimer.html"
)
