"""Offline contract tests against recorded shapes of E-utilities responses."""
from datetime import date

import pytest

import pubmed


class DummyResponse:
    def __init__(self, payload=None, content=b''):
        self.payload = payload
        self.content = content
    def json(self):
        return self.payload


def test_esearch_uses_publication_dates_and_history(monkeypatch):
    captures = []
    def fake_req(_session, endpoint, params):
        captures.append((endpoint, params))
        return DummyResponse({"esearchresult": {"count": "12001", "querytranslation": "cancer AND 2019:2026[dp]",
                                                 "webenv": "hist", "querykey": "2"}})
    monkeypatch.setattr(pubmed, '_request', fake_req)
    info = pubmed.search_window(None, 'cancer', date(2019,1,1), date(2026,12,31))
    assert info.count == 12001
    endpoint, params = captures[0]
    assert endpoint == 'esearch.fcgi'
    assert params['db'] == 'pubmed' and params['usehistory'] == 'y'
    assert params['mindate'] == '2019/01/01'
    assert params['maxdate'] == '2026/12/31'
    assert params['datetype'] == 'pdat'


def test_preview_can_fetch_from_a_large_set(monkeypatch):
    def fake_req(_session, endpoint, params):
        return DummyResponse(content=b'''<PubmedArticleSet><PubmedArticle><MedlineCitation>
        <PMID>777</PMID><Article><Journal><Title>Test</Title></Journal>
        <ArticleTitle>A title</ArticleTitle></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>''')
    monkeypatch.setattr(pubmed, '_request', fake_req)
    info = pubmed.SearchInfo(1000000, 'q', 'hist', '1', 'timestamp')
    rows = pubmed.fetch_preview_pubmed(None, info, 1)
    assert len(rows) == 1 and rows[0]['PMID'] == '777'


def test_efetch_rejects_missing_records(monkeypatch):
    monkeypatch.setattr(pubmed, '_request', lambda *_: DummyResponse(content=b'<PubmedArticleSet></PubmedArticleSet>'))
    info = pubmed.SearchInfo(1,'q','hist','1','timestamp')
    with pytest.raises(ValueError, match='expected'):
        list(pubmed.iter_pubmed_batches(None, info))


def test_efetch_must_not_silently_cap(monkeypatch):
    info = pubmed.SearchInfo(10001,'q','hist','1','timestamp')
    with pytest.raises(ValueError, match='split'):
        list(pubmed.iter_pubmed_batches(None, info))
