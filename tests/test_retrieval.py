from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from pubmed import SearchInfo
from retrieval import (IncompleteSearchError, SearchStore, Window, execute_full_search,
                       get_run_id, plan_windows, split_range)


def fake_info(count, label):
    return SearchInfo(count, label, 'history', '1', '2026-10-10T20:00:00+00:00')


def fake_rec(pmid):
    return {"PMID": str(pmid), "Title": f"Title {pmid}", "Authors": "First Author",
            "RIS Authors": ["Author, First"], "Year": "2024", "Journal": "Test Journal",
            "DOI": f"10.1111/{pmid}", "Abstract": "abstract", "PubMed URL": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "Source": "PubMed"}


def test_contiguous_date_splits():
    first, second = split_range(date(2020, 1, 1), date(2020, 1, 4))
    assert first == (date(2020, 1, 1), date(2020, 1, 2))
    assert second == (date(2020, 1, 3), date(2020, 1, 4))
    with pytest.raises(IncompleteSearchError):
        split_range(date(2020, 1, 1), date(2020, 1, 1))


def test_plan_over_10000_exhaustive_split():
    calls = []

    def search(_session, _query, a, b):
        calls.append((a, b))
        # 2020/01/01..2020/12/31: 2 equal-sized windows
        if (b - a).days > 200:
            return fake_info(12000, 'root')
        return fake_info(6000, 'part')

    root, wins = plan_windows(None, 'diabetes', date(2020,1,1), date(2020,12,31), search_fn=search)
    assert root.count == 12000
    assert len(wins) == 2
    assert sum(x.count for x in wins) == root.count
    assert wins[0].end < wins[1].start
    assert len(calls) == 3


def test_plan_rejects_unsplittable_day():
    with pytest.raises(IncompleteSearchError, match='single|More than'):
        plan_windows(None, 'x', date(2020,3,4), date(2020,3,4),
                     search_fn=lambda *args: fake_info(12000, 'x'))


def test_plan_rejects_nonmatching_totals():
    def search(_s, _q, a, b):
        if (b-a).days > 200:
            return fake_info(12000, 'root')
        return fake_info(5900, 'part')
    with pytest.raises(IncompleteSearchError, match='counts'):
        plan_windows(None, 'x', date(2020,1,1), date(2020,12,31), search_fn=search)


def test_checkpoint_resume_and_all_ids(tmp_path):
    saved = SearchStore(tmp_path/'checkpoint.db')
    calls = {"batch": 0}
    next_id = {"count": 0}

    def search(_s, _q, a, b):
        if (b-a).days > 200:
            return fake_info(12000, 'root')
        return fake_info(6000, 'part')

    def flaky_batches(_session, info):
        calls["batch"] += 1
        if calls['batch'] == 2:
            raise ConnectionError('temporary outage')
        start = next_id['count'] + 1
        next_id['count'] += info.count
        yield [fake_rec(i) for i in range(start, start + info.count)], info.count, info.count

    try:
        with pytest.raises(ConnectionError):
            execute_full_search(None, saved, 'test', 2020, 2020, search_fn=search, batch_fn=flaky_batches)
        run_id = get_run_id('test',2020,2020)
        assert saved.record_count(run_id) == 6000
        assert [x['status'] for x in saved.windows(run_id)] == ['done','pending']
        assert saved.run(run_id)['status'] == 'running'
        def resume_batches(_s, info):
            start = next_id['count'] + 1
            next_id['count'] += info.count
            yield [fake_rec(i) for i in range(start, start+info.count)], info.count, info.count
        resume_id = execute_full_search(None, saved, 'test', 2020,2020,
                                        search_fn=search, batch_fn=resume_batches)
        assert resume_id == run_id
        assert saved.record_count(run_id) == 12000
        assert saved.run(run_id)['status'] == 'complete'
        assert len(saved.sample(run_id)) == 100
        assert len(list(saved.iter_records(run_id))) == 12000
    finally:
        saved.close()


def test_index_change_rejected(tmp_path):
    db = SearchStore(tmp_path/'job.db')
    def search(_s, _q, a, b):
        if (b-a).days > 200:
            return fake_info(12000, 'root')
        search.calls += 1
        return fake_info(5999 if search.calls > 2 else 6000, 'part')
    search.calls = 0
    try:
        with pytest.raises(IncompleteSearchError, match='changed'):
            execute_full_search(None, db, 'query', 2020, 2020, search_fn=search)
    finally:
        db.close()


def test_cross_window_duplicate_not_complete(tmp_path):
    db = SearchStore(tmp_path/'job.db')
    try:
        run_id = 'run-test'
        db.create(run_id, 'diabetes', 2024,2024, fake_info(2,'query'),
                  [Window(date(2024,1,1),date(2024,3,1),1),
                   Window(date(2024,3,2),date(2024,12,31),1)])
        wins = db.windows(run_id)
        db.checkpoint(run_id, wins[0], [fake_rec(100)])
        db.checkpoint(run_id, wins[1], [fake_rec(100)])
        assert not db.finalize(run_id)
        assert db.run(run_id)['status'] == 'incomplete'
    finally:
        db.close()


def test_clear_and_fresh(tmp_path):
    db = SearchStore(tmp_path/'db')
    try:
        db.create('a','x',2025,2025,fake_info(1,'root'),[Window(date(2025,1,1),date(2025,12,31),1)])
        db.checkpoint('a',db.windows('a')[0],[fake_rec(99)])
        db.clear('a')
        assert db.run('a') is None
        assert db.record_count('a') == 0
    finally:
        db.close()
