#!/usr/bin/env python3
"""Verify the API key and every model id the config routes to.

The analysis stage swallows per-item errors and scores the item None, so a
wrong model id or a bad key produces an empty briefing that reads exactly like
a quiet news day. This makes that failure explicit and cheap to find.

    ANTHROPIC_API_KEY=... uv run python scripts/check-models.py

Costs a handful of tokens per configured model (one 5-token completion each).
Never prints the key.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai.retrying import describe_ai_error

CONFIG_PATH = Path("data/config.json")


def configured_models() -> tuple[str, dict[str, str], str, str]:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        ai = json.load(f)["ai"]
    return (
        ai["model"],
        ai.get("stage_models", {}),
        ai.get("api_key_env", "ANTHROPIC_API_KEY"),
        ai.get("workspace_id_env", "ANTHROPIC_WORKSPACE_ID"),
    )


async def main() -> int:
    if not CONFIG_PATH.exists():
        print("data/config.json 이 없습니다. 먼저: cp data/config.github.json data/config.json")
        return 2

    base_model, stage_models, key_env, workspace_env = configured_models()
    key = os.environ.get(key_env)
    if not key:
        print(f"환경변수 {key_env} 가 비어 있습니다.")
        print(f"  export {key_env}='...'  후 다시 실행하세요.")
        return 2
    print(f"{key_env}: 설정됨")

    workspace_id = (os.environ.get(workspace_env) or "").strip()
    print(f"{workspace_env}: {workspace_id or '미설정'}\n")

    import anthropic

    headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
    client = anthropic.AsyncAnthropic(api_key=key, default_headers=headers)

    print("=== 계정에서 사용 가능한 모델 ===")
    available: set[str] = set()
    try:
        async for model in client.models.list():
            available.add(model.id)
            print(f"  {model.id}")
    except Exception as e:
        message = str(e)
        print(f"  모델 목록 조회 실패: {describe_ai_error(e)}")
        if "workspace" in message.lower():
            # Identity-linked keys are scoped to a workspace and reject every
            # request until that workspace is named in a header.
            print(
                f"\n  이 키는 워크스페이스 지정이 필요한 identity-linked 키입니다.\n"
                f"  console.anthropic.com 에서 워크스페이스 id(wrkspc_... 형태)를 확인해\n"
                f"  {workspace_env} 로 넣으세요. GitHub Actions 에서는 같은 이름의\n"
                f"  시크릿을 등록하면 됩니다."
            )
        else:
            print("  키가 유효하지 않거나 권한이 없을 수 있습니다.")
        return 1

    targets = {"요약(ai.model)": base_model}
    for stage, model in stage_models.items():
        targets[f"{stage}(stage_models)"] = model

    print("\n=== 설정된 모델 실제 호출 ===")
    failed = 0
    for label, model in targets.items():
        listed = "목록에 있음" if model in available else "목록에 없음"
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=5,
                messages=[{"role": "user", "content": "Reply with the single word: ok"}],
            )
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            print(f"  OK   {label:<26} {model:<26} ({listed}) -> {text!r}")
        except Exception as e:
            failed += 1
            print(f"  FAIL {label:<26} {model:<26} ({listed})")
            print(f"         {describe_ai_error(e)}")

    if failed:
        print(f"\n{failed}개 모델이 호출에 실패했습니다.")
        print("data/config.github.json 의 ai.model / ai.stage_models 를")
        print("위 '사용 가능한 모델' 목록의 id 로 바꾸세요.")
        return 1

    print("\n설정된 모델 전부 정상 호출됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
