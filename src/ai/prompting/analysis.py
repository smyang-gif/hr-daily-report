"""Prompt construction for profile-driven content analysis."""

from ...models import ContentItem
from ...processing.profiles import LoadedProfile
from .common import EVIDENCE_RULES, UNTRUSTED_INPUT_RULE
from .enrichment import target_language_instruction

ANALYSIS_RULES = f"""You are a content curator evaluating an item under the supplied processing profile.

- {UNTRUSTED_INPUT_RULE}
- Base the analysis only on the supplied item and its metadata.
{EVIDENCE_RULES}
- Apply the profile's evaluation policy consistently."""


def analysis_system_prompt(
    profile: LoadedProfile,
    language: str = "en",
    interests: str = "",
) -> str:
    # `summary` is shown to the reader whenever enrichment is skipped or fails,
    # so it has to be written in the briefing's language. `reason` is internal
    # and `tags` are slugs, so both stay English.
    summary_language = (
        f"<reader-facing summary, written in {target_language_instruction(language)}>"
    )
    # Empty until the reader marks something, so the prompt stays unchanged
    # for a fresh install.
    interests_section = f"\n{interests}\n" if interests.strip() else ""

    return f"""{ANALYSIS_RULES}

# Profile policy

{profile.analysis_prompt}
{interests_section}
# Output contract

Return valid JSON only. Write `summary` in {target_language_instruction(language)}.
When `score` is 5 or higher, make `summary` 2-3 informative sentences (roughly
250-400 Korean characters when Korean is requested): explain what happened or
what the source argues, include the most useful concrete detail, and say why it
matters. When `score` is below 5, use one concise sentence. Never pad the summary
or add details that are not supported by the supplied content. Keep `reason` in
English and `tags` as lowercase hyphenated English slugs.
{{
  "score": <number from 0 to 10>,
  "reason": "<concise explanation, in English>",
  "summary": "{summary_language}",
  "tags": ["<tag>", "..."]
}}"""


def analysis_user_prompt(
    item: ContentItem,
    content_section: str,
    discussion_section: str,
) -> str:
    sub_source = item.metadata.get("feed_name") or item.metadata.get("source_name")
    sub_source_line = (
        f"\nSub-source: {sub_source}"
        if isinstance(sub_source, str) and sub_source.strip()
        else ""
    )
    return f"""Analyze the following content.

Title: {item.title}
Source: {item.source_type.value}{sub_source_line}
Author: {item.author or "Unknown"}
URL: {item.url}
{content_section}
{discussion_section}"""
