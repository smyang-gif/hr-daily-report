from src.ai.analyzer import ContentAnalyzer
from src.models import ContentAnalysis


def test_summary_sentence_list_is_flattened() -> None:
    result = ContentAnalysis.model_validate(
        {"score": 7, "reason": "r", "summary": ["첫 문장.", "둘째 문장."], "tags": []}
    )
    assert result.summary == "첫 문장. 둘째 문장."


def test_summary_language_object_is_flattened() -> None:
    result = ContentAnalysis.model_validate(
        {"score": 7, "reason": "r", "summary": {"ko": "요약"}, "tags": []}
    )
    assert result.summary == "요약"


def test_null_summary_keeps_the_score() -> None:
    result, failure = ContentAnalyzer._validate_analysis_response(
        '{"score": 3, "reason": "r", "summary": null, "tags": []}'
    )
    assert failure == ""
    assert result is not None and result.score == 3
