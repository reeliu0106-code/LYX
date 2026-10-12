import json
import zipfile
from datetime import date

import pytest

from covidence_export import MAX_RIS_BYTES, MAX_RIS_REFERENCES, ris_entry, write_covidence_bundle
from retrieval import SearchStore, Window
from pubmed import SearchInfo, parse_pubmed_xml


def rec(pmid):
    return {"PMID": str(pmid), "Title": f"Title {pmid}", "Authors": "Jill Smith; Anne Doe",
            "RIS Authors": ["Smith, Jill", "Doe, Anne"], "Year": "2026", "Journal": "Journal of Medicine",
            "Journal Abbrev": "J Med", "Volume": "8", "Issue": "4", "Start Page": "100",
            "End Page": "110", "DOI": f"10.1000/{pmid}", "Abstract": "Background\nResults",
            "PubMed URL": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "Source": "PubMed"}


def test_ris_bibliographic_fields_and_utf8():
    record = rec(123)
    record['Title'] = '饮食干预 Study'
    output = ris_entry(record).decode('utf-8')
    assert output.startswith('TY  - JOUR\r\n')
    assert 'AU  - Smith, Jill' in output
    assert 'TI  - 饮食干预 Study' in output
    assert 'JO  - Journal of Medicine' in output
    assert 'VL  - 8' in output and 'IS  - 4' in output
    assert 'SP  - 100' in output and 'EP  - 110' in output
    assert 'AB  - Background Results' in output
    assert 'DO  - 10.1000/123' in output
    assert output.endswith('ER  - \r\n\r\n')


def test_bad_metadata_prevents_ris():
    with pytest.raises(ValueError):
        ris_entry({"Title": "A"})


def make_store(path, complete):
    db = SearchStore(path)
    db.create('id','T2DM',2024,2024,
              SearchInfo(5, 'query translation','webenv','key','2026-10-10T11:00:00Z'),
              [Window(date(2024,1,1),date(2024,12,31),5)])
    db.checkpoint('id',db.windows('id')[0],[rec(i) for i in range(1,6)])
    if complete:
        assert db.finalize('id')
    return db


def test_zip_chunking_csv_and_audit(tmp_path):
    db = make_store(tmp_path/'db',True)
    try:
        output = tmp_path/'covidence.zip'
        audit = write_covidence_bundle(db,'id',output,max_references=2,max_bytes=600)
        assert [x['records'] for x in audit['ris_parts']] == [2,2,1]
        assert audit['certified_complete_at_initial_count'] is True
        with zipfile.ZipFile(output) as z:
            names = z.namelist()
            assert len([n for n in names if n.endswith('.ris')]) == 3
            assert 'pubmed_records.csv' in names
            assert 'search_audit.json' in names
            assert '\r\n' in z.read('covidence_pubmed_part_001.ris').decode('utf-8')
            assert z.read('covidence_pubmed_part_001.ris').decode('utf-8').count('TY  - JOUR') == 2
            assert 'T2DM' in z.read('search_audit.json').decode('utf-8')
            assert z.read('pubmed_records.csv').startswith(b'\xef\xbb\xbf')
    finally:
        db.close()


def test_incomplete_export_is_blocked_by_default(tmp_path):
    db=make_store(tmp_path/'db',False)
    try:
        with pytest.raises(ValueError, match='not certified'):
            write_covidence_bundle(db,'id',tmp_path/'bad.zip')
        result=write_covidence_bundle(db,'id',tmp_path/'partial.zip',allow_incomplete=True)
        assert result['certified_complete_at_initial_count'] is False
        with zipfile.ZipFile(tmp_path/'partial.zip') as z:
            assert any(x.startswith('INCOMPLETE_') for x in z.namelist())
    finally:
        db.close()


def test_bibliographic_xml_parser_extra_fields():
    xml = b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>789</PMID><Article>
      <Journal><ISSN>1234-4567</ISSN><JournalIssue><Volume>10</Volume><Issue>2</Issue>
      <PubDate><Year>2024</Year></PubDate></JournalIssue><Title>Journal</Title>
      <ISOAbbreviation>J Test</ISOAbbreviation></Journal>
      <ArticleTitle>Test</ArticleTitle><Pagination><MedlinePgn>12-15</MedlinePgn></Pagination>
      <AuthorList><Author><LastName>Zhang</LastName><ForeName>Wei</ForeName></Author></AuthorList>
      </Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'''
    row = parse_pubmed_xml(xml)[0]
    assert row['RIS Authors'] == ['Zhang, Wei']
    assert row['Volume']=='10' and row['Issue']=='2'
    assert row['Start Page']=='12' and row['End Page']=='15'
    assert row['Journal Abbrev']=='J Test' and row['ISSN']=='1234-4567'


def test_max_constraints():
    assert MAX_RIS_REFERENCES == 15000
    assert MAX_RIS_BYTES < 50 * 1024 * 1024


def test_book_record_has_book_type():
    sample=b'''<PubmedArticleSet><PubmedBookArticle><BookDocument>
      <PMID>123456</PMID><ArticleIdList></ArticleIdList>
      <Book><BookTitle>Nutrition Handbook</BookTitle><PubDate><Year>2020</Year></PubDate></Book>
      <ArticleTitle>Dietary Interventions</ArticleTitle>
      <AuthorList><Author><LastName>Li</LastName><ForeName>Min</ForeName></Author></AuthorList>
      </BookDocument></PubmedBookArticle></PubmedArticleSet>'''
    row=parse_pubmed_xml(sample)[0]
    assert row['RIS Type']=='CHAP'
    assert row['Title']=='Dietary Interventions'
    assert row['Year']=='2020'
    assert ris_entry(row).startswith(b'TY  - CHAP')
