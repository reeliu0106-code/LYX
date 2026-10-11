import xml.etree.ElementTree as ET

from pubmed import parse_pubmed_xml, to_ris, _get_year


SAMPLE_XML = b"""<?xml version='1.0' encoding='UTF-8'?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345</PMID>
      <Article>
        <Journal><JournalIssue><PubDate><Year>2024</Year></PubDate></JournalIssue><Title>Sample Journal</Title></Journal>
        <ArticleTitle>Test <i>Dietary</i> Intervention</ArticleTitle>
        <Abstract><AbstractText Label="BACKGROUND">Study context.</AbstractText><AbstractText Label="RESULTS">Findings here.</AbstractText></Abstract>
        <AuthorList><Author><LastName>Wang</LastName><ForeName>Min</ForeName></Author><Author><CollectiveName>Research Group</CollectiveName></Author></AuthorList>
      </Article>
    </MedlineCitation>
    <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1234/test</ArticleId></ArticleIdList></PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""


def test_parser_extracts_bibliographic_metadata():
    items = parse_pubmed_xml(SAMPLE_XML)
    assert len(items) == 1
    item = items[0]
    assert item["PMID"] == "12345"
    assert item["Year"] == "2024"
    assert item["DOI"] == "10.1234/test"
    assert item["Title"] == "Test Dietary Intervention"
    assert item["Authors"] == "Min Wang; Research Group"
    assert "BACKGROUND: Study context." in item["Abstract"]
    assert item["PubMed URL"].endswith("12345/")


def test_export_ris():
    ris = to_ris(parse_pubmed_xml(SAMPLE_XML))
    assert "TY  - JOUR" in ris
    assert "TI  - Test Dietary Intervention" in ris
    assert "DO  - 10.1234/test" in ris
    assert "ER  - " in ris


def test_parse_empty():
    assert parse_pubmed_xml(b"<PubmedArticleSet></PubmedArticleSet>") == []


def test_year_fallback_medline_date():
    item = ET.fromstring("<PubmedArticle><MedlineCitation><Article><Journal><JournalIssue><PubDate><MedlineDate>2019 Jan-Feb</MedlineDate></PubDate></JournalIssue></Journal></Article></MedlineCitation></PubmedArticle>")
    assert _get_year(item) == "2019"
