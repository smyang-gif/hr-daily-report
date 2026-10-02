"""Markdown escaping must stay safe without mangling ordinary punctuation."""

from __future__ import annotations

from src.ai.summarizer import _escape_markdown


def test_apostrophes_and_quotes_survive_literally() -> None:
    # html.escape(quote=True) turns these into &#x27; / &quot;, and the later
    # Markdown pass escapes the "#" into &\#x27;, which readers see verbatim.
    assert _escape_markdown("OpenAI's 'critical risk' rating") == (
        "OpenAI's 'critical risk' rating"
    )
    assert _escape_markdown('say "hi"') == 'say "hi"'


def test_html_is_still_neutralised() -> None:
    escaped = _escape_markdown("<script>alert(1)</script>")

    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped


def test_ampersand_is_still_escaped() -> None:
    assert _escape_markdown("A & B") == "A &amp; B"


def test_markdown_control_characters_are_escaped() -> None:
    escaped = _escape_markdown("**bold** [link](url) # heading")

    assert "\\*\\*bold\\*\\*" in escaped
    assert "\\[link\\]" in escaped
    assert "\\#" in escaped


def test_no_stray_numeric_entities_remain() -> None:
    # The regression this guards: a numeric entity whose "#" gets escaped.
    for text in ["it's", 'a "b" c', "don't — can't"]:
        assert "&#" not in _escape_markdown(text)
        assert "&\\#" not in _escape_markdown(text)
