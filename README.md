# hr-daily-report

## [📋 HR 데일리 브리핑 바로 보기](https://smyang-gif.github.io/hr-daily-report/)

채용·인재시장·HR테크·노동정책 소식을 매일 오전 9시(KST) 한국어 브리핑으로 정리해 GitHub Pages에 쌓는 개인용 파이프라인입니다.
[Thysrael/Horizon](https://github.com/Thysrael/Horizon)(MIT)과 그 포크 [maestrokurtc-oss/ai-researcher](https://github.com/maestrokurtc-oss/ai-researcher)를 바탕으로 했습니다.

## 동작 방식

```
GitHub Actions (23:37 UTC = 08:37 KST, 실패 대비 10:17 KST 재시도)
  └─ 수집  최근 24시간 · 국내 뉴스 검색 3종 · 고용노동부 · 매일노동뉴스
          · HR Dive · HR Tech Feed · Personnel Today · ERE · Josh Bersin
          · Aptitude Research · Indeed Hiring Lab · Recruiting Brainfood · HBR · MIT SMR
  └─ 채점  Haiku 4.5 로 중요도 0~10 + 프로필 분류
  └─ 선별  프로필별 임계값 통과분, 주제 중복 제거(Sonnet 5), 최대 20건
  └─ 요약  Sonnet 5 로 한국어 요약
  └─ 산출  briefings/YYYY/MM/YYYY-MM-DD.md 커밋 + GitHub Pages 배포
```

## 프로필 (채점·요약 기준)

| 프로필 | 다루는 것 | 임계값 |
|---|---|---|
| `hr-news` 채용·인재시장 동향 | 채용·감원, 채용 수요 데이터, HR테크·채용툴 출시·투자, AI 채용 | 6.0 |
| `hr-policy` 노동정책·규제 | 고용노동부, 근로기준법, 최저임금, AI 채용·후보자 데이터 규제 | 6.0 |
| `hr-insight` 리서치·인사이트 | 리서치 리포트, 뉴스레터, 장문 분석 | 6.5 |

프롬프트는 `profiles/<id>/`, 소스·임계값은 `data/config.github.json`에서 고칩니다.

## 설정

1. 저장소 → Settings → Secrets and variables → Actions → `ANTHROPIC_API_KEY` 등록
2. Settings → Pages → Source: `gh-pages` 브랜치 `/ (root)` (첫 실행 후 브랜치가 생깁니다)
3. Actions → HR Briefing → Run workflow 로 수동 실행 가능 (`force`로 재생성)

## 로컬 실행

```bash
uv sync
cp data/config.github.json data/config.json
uv run python scripts/check-sources.py --feeds   # 피드 상태만 확인 (비용 0)
ANTHROPIC_API_KEY=... uv run python -m src.main  # 전체 실행
```
