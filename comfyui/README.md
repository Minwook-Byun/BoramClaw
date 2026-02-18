# ComfyUI 도식화 세팅

이 폴더는 BoramClaw 아키텍처를 **도식 이미지로 생성**하기 위한 ComfyUI 자산입니다.

## 포함 파일
- `workflows/boramclaw_architecture_api.json`
- `prompts/boramclaw_architecture_prompt_ko.txt`

## 사용 방법 (ComfyUI API 포맷)
1. ComfyUI 실행
2. `workflows/boramclaw_architecture_api.json` 내용을 Load/Import
3. `CheckpointLoaderSimple`의 `ckpt_name`을 로컬 모델명으로 변경
4. 실행(Queue Prompt)

기본 출력 경로:
- `ComfyUI/output/boramclaw/architecture_*.png`

## 권장 모델
- SDXL 계열 (`sd_xl_base_1.0.safetensors`)
- Flux 계열 사용 시 노드 구성이 달라질 수 있으므로 프롬프트만 재사용 권장

