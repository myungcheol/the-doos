# Jokbo OCR v6.3 — 관계선 확인 + 고정 검수 패널 + 인물 정보 OCR 초안

전통 한자 세로쓰기 족보 스캔본을 대상으로 하는 LLM 없는 OCR 및 검수 도구입니다.

- **OpenCV**: 표/행/인명 영역 검출
- **PaddleOCR 3.x / PP-OCRv5**: 기본 OCR 엔진
- **Python 규칙**: 족보 판면 규칙을 이용한 부모·자녀 관계 후보 생성 및 인물 정보 초안 추출
- **Streamlit**: 브라우저에서 인명 판독과 부모·자녀 연결을 검수
- **JSON / CSV**: 검수 결과 내보내기

모든 OCR 및 자동 추출 후보는 사람이 확인하기 전까지 미검수 상태입니다. OCR Confidence는 정답 확률이 아닙니다.

## v6.3 변경 사항

### 1. 부모를 선택하면 기존 관계선 강조

- 부모 선택 시 그 부모에게 이미 연결된 **확정 관계**를 굵은 파란색 선과 화살표로 강조합니다.
- 자동 생성됐지만 아직 확인하지 않은 부모·자녀 후보도 해당 부모를 선택한 경우 주황색 선으로 표시합니다.
- 이미지 위에는 확정 자녀와 검토 대기 자녀를 이름으로 나누어 표시합니다.
- 평소에는 확정 관계를 초록색 선으로 표시합니다. 거절된 후보는 표시하지 않습니다.
- 부모 선택 상태는 이전 v6.2처럼 여러 자녀를 연속해서 연결할 수 있도록 유지됩니다.

### 2. 오른쪽 검수 영역만 내부 스크롤

- 원본 페이지는 왼쪽 열에 둡니다.
- 인명/관계 입력 패널은 고정 높이의 Streamlit scroll container로 만들었습니다. 긴 폼을 오른쪽 영역 안에서 스크롤해도 왼쪽의 원본 페이지는 같은 위치에 남습니다.
- 사이드바의 `오른쪽 검수 패널 높이`에서 500~1,000px로 조절할 수 있습니다.
- 이 기능은 `st.container(height=..., key=...)`를 사용하므로 `streamlit>=1.47`이 필요합니다.

### 3. 기존 OCR 텍스트로 인물 정보 자동 초안

새 PaddleOCR 추론을 다시 실행하지 않습니다. 기존 `ocr_results.json`에 저장된 각 세로 OCR 열의 텍스트와 bbox 좌표를 재사용합니다.

1. 인물 이름 영역의 x좌표를 찾습니다.
2. 같은 행의 인물 이름 영역들을 오른쪽부터 정렬합니다.
3. 각 인물 이름 바로 왼쪽부터 다음 인물 이름 영역까지의 OCR 열을 해당 인물의 기록 구간으로 간주합니다.
4. 해당 구간의 텍스트에서 `生`, `卒`, `官至`, `進士`, `配`, `夫人`, `葬`, `墓` 등의 표식을 찾아 주변 OCR 열 텍스트를 모읍니다.
5. 다음 필드에 검수용 초안을 채웁니다.
   - 출생 정보 / 사망 정보
   - 관직·품계·봉호
   - 배우자
   - 묘소·장지
   - 자(字) / 호(號)
   - 인물 기록 원문 전체

인물 검수 탭에서 `OCR로 인물 정보 초안 채우기`를 누르면 빈 필드만 채웁니다. 기존에 사용자가 입력한 값은 덮어쓰지 않습니다. 자동 추출 근거가 된 OCR 영역과 키워드 주변 텍스트도 함께 보여줍니다.

**중요한 제한:** 이 기능은 레이아웃 좌표와 키워드에 기반한 규칙 추출입니다. 족보 판면이 다르거나 인물 기록이 여러 열에 걸쳐 있으면 다른 인물의 텍스트가 포함될 수 있습니다. OCR 오인식도 그대로 반영됩니다. 필드 값은 날짜 변환이나 사실 검증을 거치지 않은 원문 초안이므로 원본 이미지와 대조해야 합니다. 해당 인물의 기록 열을 분리하지 못한 경우에는 필드를 임의로 채우지 않습니다.

추가로 `추가 인물 정보(OCR 초안 포함)를 원본과 대조했습니다` 체크박스를 넣었습니다. 이름 판독 승인과 인물 정보 확인 상태를 별도로 저장합니다.

## v6.2에서 업그레이드

- 기존 `review_state.json`을 그대로 사용할 수 있습니다.
- 검수 데이터 구조를 초기화하거나 OCR을 다시 실행할 필요는 없습니다.
- 기존 v6.2 프로젝트에 업데이트할 때는 `review_app.py`, `person_info_extractor.py`, `requirements-review.txt`를 교체/추가하면 됩니다.
- 자동 추출 초안은 인물의 `people_updates`에 별도로 저장되며, 원본 OCR 후보 파일은 변경하지 않습니다.

## 설치

Python 3.10~3.13 환경을 권장합니다. PaddleOCR CPU 환경에서 이미 정상 동작하는 `.venv-paddle` 환경이 있다면 그대로 사용하면 됩니다.

검수 UI 의존성을 설치하거나 업데이트합니다.

```bash
source .venv-paddle/bin/activate
pip install -r requirements-review.txt
```

`requirements-review.txt`는 `streamlit>=1.47`과 `streamlit-image-coordinates>=0.3.0`을 설치합니다. 이미 PaddleOCR가 설치되어 있으면 PaddleOCR 설치를 반복할 필요는 없습니다.

## OCR 실행

일반적인 작업에서는 PaddleOCR만 실행합니다.

```bash
python jokbo_ocr.py ./scan/ \
  --ocr-engine paddleocr \
  --paddle-version PP-OCRv5 \
  --paddle-lang chinese_cht \
  --paddle-device cpu \
  --rows 6 \
  --output output/
```

특정 이미지 한 장만 실행하려면:

```bash
python jokbo_ocr.py ./scan/001.jpg \
  --ocr-engine paddleocr \
  --rows 6 \
  --output output/
```

## 검수 UI 실행

프로젝트 폴더에서:

```bash
streamlit run review_app.py
```

브라우저에서 `http://localhost:8501`을 열고 왼쪽의 OCR 결과 디렉터리에 `output`을 입력합니다. `--ocr-engine both --output compare/`로 실행했다면 `compare/paddleocr`를 입력합니다.

### 부모·자녀 관계 검수

1. 사이드바 모드를 `부모 → 자녀 연결`로 선택합니다.
2. 원본 페이지에서 부모 인물 박스를 클릭합니다.
3. 해당 부모에게 연결할 자녀를 차례대로 클릭합니다.
4. 선택한 부모에게 기존 확정 관계가 있으면 파란색 선과 화살표로 강조됩니다. 검토 대기 후보는 주황색 선으로 표시됩니다.
5. 완료 후 `부모 선택 취소`를 누릅니다.

### 인물 정보 자동 초안 및 검수

1. 사이드바 모드를 `인물 선택 / 이름 검수`로 선택합니다.
2. 이미지의 인명 박스 또는 오른쪽 `인물 선택`에서 인물을 고릅니다.
3. `OCR로 인물 정보 초안 채우기`를 누릅니다.
4. OCR로 추출된 원문 영역과 필드별 근거를 확인합니다.
5. 자동 입력된 출생·사망·관직·배우자·묘소 등의 필드를 원본 이미지와 대조해 수정합니다.
6. 이름 확인과 추가 인물 정보 확인 체크박스를 각각 선택한 뒤 저장합니다.

## 출력 파일

```text
output/
├── ocr_results.json
├── people_candidates.json
├── relationship_candidates.json
├── reviewed_people.json          # UI에서 생성/갱신
├── reviewed_people.csv           # 정보 확인 상태와 OCR 원문 기록 포함
├── reviewed_relationships.json   # UI에서 생성/갱신
├── reviewed_relationships.csv    # UI에서 생성/갱신
├── review_state.json             # UI에서 생성/갱신
└── ...
```

검수 UI는 원본 `people_candidates.json`, `relationship_candidates.json`, `ocr_results.json`을 덮어쓰지 않습니다. 변경사항은 `review_state.json`에 저장하며 검수 완료 데이터는 별도의 `reviewed_*` 파일로 내보냅니다.

## 테스트

```bash
python -m unittest discover -s tests -v
```

테스트는 PaddleOCR 어댑터/추론 최적화, 관계 배치 규칙, 인물별 OCR 열 분리 및 필드 키워드 추출을 포함합니다.
