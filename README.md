# Jokbo OCR

전통 한자 세로쓰기 족보 스캔본을 OCR로 읽고, 인물 후보와 부모·자녀 관계를 추출한 뒤, 원본 이미지와 대조해 검수하는 Python 프로젝트입니다.

이 파일 하나를 프로젝트의 공식 README로 사용합니다. 이전 버전별 README는 별도로 관리하지 않아도 됩니다.

---

## 목차

1. [프로젝트 목표와 처리 흐름](#1-프로젝트-목표와-처리-흐름)
2. [주요 기능](#2-주요-기능)
3. [설치](#3-설치)
4. [OCR 실행](#4-ocr-실행)
5. [OCR 결과 파일](#5-ocr-결과-파일)
6. [검수 UI 실행과 사용법](#6-검수-ui-실행과-사용법)
7. [인물 정보 자동 추출](#7-인물-정보-자동-추출)
8. [데이터 모델: 원본·검수·고유 ID](#8-데이터-모델-원본검수고유-id)
9. [부모·자녀 관계 추출 규칙](#9-부모자녀-관계-추출-규칙)
10. [검수 결과 및 내보내기 파일](#10-검수-결과-및-내보내기-파일)
11. [성능 확인](#11-성능-확인)
12. [테스트](#12-테스트)
13. [문제 해결](#13-문제-해결)
14. [현재 한계와 검수 원칙](#14-현재-한계와-검수-원칙)
15. [버전별 기능 이력](#15-버전별-기능-이력)
16. [프로젝트 파일 구성](#16-프로젝트-파일-구성)
17. [처음 참여하는 개발자를 위한 빠른 시작](#17-처음-참여하는-개발자를-위한-빠른-시작)
18. [소스 코드와 데이터 찾아보기](#18-소스-코드와-데이터-찾아보기)
19. [안전한 개발 및 검수 절차](#19-안전한-개발-및-검수-절차)

---

## 1. 프로젝트 목표와 처리 흐름

이 프로젝트는 OCR 텍스트를 만드는 데서 끝나지 않고, 장기적으로 족보의 인물·출처·가족관계를 구조화하는 것을 목표로 합니다.

- **OpenCV**: 족보 표 영역, 가로 행, 세로 텍스트 열, 인명 후보 영역 검출
- **PaddleOCR 3.x**: 세로쓰기 한자 본문과 인명 OCR
- **Python 규칙**: 인명 후보 정리, 부모·자녀 관계 후보, 인물별 기록 영역과 정보 초안 추출
- **PySide6**: 원본 스캔을 보면서 인명과 관계를 검수하는 데스크톱 UI
- **JSON / CSV**: OCR 원문, 검수 정보, 판본별 출처, 영구 인물 ID, 관계를 내보내기

전체 흐름은 다음과 같습니다.

```text
족보 스캔 이미지
      |
      v
OpenCV: 표 영역 및 행 분할
      |
      v
세로 열 검출 및 OCR
      |
PaddleOCR 3.x
      |
      v
                  공통 텍스트 / 좌표 / confidence
                             |
                             v
                 인명 영역 검출 및 OCR 후보
                             |
                             v
                Python 규칙 기반 관계 후보 생성
                             |
                             v
                JSON / CSV 원본 후보 파일 저장
                             |
                             v
                  PySide6 검수 UI 실행
                             |
             +---------------+----------------+
             |                                |
             v                                v
        인물 정보 검수                    관계 검수
             |                                |
             +---------------+----------------+
                             |
                             v
               Raw Data + Reviewed Data
                             |
                             v
            영구 person_uid / 출처 / 관계 내보내기
```

**LLM이나 외부 생성형 AI API는 사용하지 않습니다.** PaddleOCR 모델 파일은 최초 실행 시 다운로드될 수 있으므로, PaddleOCR 초기 설치 및 첫 실행에는 인터넷 연결이 필요할 수 있습니다.

## 2. 주요 기능

### OCR과 레이아웃

- 단일 이미지 파일 또는 이미지 폴더를 입력할 수 있습니다.
- JPG, JPEG, PNG, TIF, TIFF, BMP, WEBP 형식을 지원합니다.
- 표 외곽과 가로 행을 검출하고, 각 행 내부의 세로 열을 재구성합니다.
- 인명 후보는 글자 크기, 연결 요소, 세로 간격, x좌표 군집 등 이미지 기하 정보를 이용해 검출합니다.
- PaddleOCR 3.x로 본문과 인명 후보를 읽습니다.

### PaddleOCR 추론 최적화

v5까지는 행 OCR 이후 각 인명 crop에 여러 전처리를 적용해 반복 추론하는 방식이었습니다. v6부터는 다음 순서를 사용합니다.

1. 각 행을 먼저 OCR합니다.
2. 행 OCR 결과의 글자 좌표와 인명 bbox를 가로·세로 방향으로 매칭합니다.
3. 이름 후보가 적절한 글자 수와 confidence 기준을 만족하면 행 OCR 결과를 재사용합니다.
4. 매칭되지 않거나 기준 미달인 인명만 crop OCR을 추가 실행합니다.
5. 추가 OCR은 CLAHE부터 시도하고, 결과가 계속 기준 미달일 때 Otsu, Adaptive Threshold, 90도 회전 이미지를 순서대로 시도합니다.

기본 재사용/중단 confidence 기준은 70입니다. 실제 추론 횟수와 처리 시간은 `paddleocr_metrics_pages.csv`에서 확인할 수 있습니다.

### 인물 및 가족관계 검수

- 원본 이미지 위에서 인물을 선택할 수 있습니다.
- 이미지와 인물/관계 검수 패널은 나란히 배치됩니다.
- 줌/팬은 데스크톱 이미지 뷰에서 처리하며 원본 이미지 좌표를 유지합니다.
- 오른쪽 검수 패널은 별도 스크롤 영역이므로, 긴 인물 정보를 편집해도 왼쪽 이미지가 계속 보입니다.
- 이미지 위의 `+` / `−` 버튼이나 `Ctrl+마우스휠`로 확대·축소하고 현재 확대율을 확인할 수 있습니다.
- 확대 상태에서는 이미지를 드래그해 이동할 수 있습니다.
- OCR 원문과 사람의 검수 결과를 별도로 보존합니다.
- 출생/사망/관직/배우자/묘소 등 선택한 필드의 OCR source bbox를 원본 이미지 좌표로 직접 그립니다. 구버전 초안에 필드 bbox가 없으면 인물 기록 영역 전체를 표시해 빈 화면이 되지 않도록 합니다.
- OCR 박스에 마우스를 올리면 인식된 전체 텍스트가 이미지 위의 별도 영역에 표시됩니다. 박스 옆에 글자를 겹쳐 그리지 않습니다.
- 한 부모에게 여러 자녀를 연속으로 연결할 수 있습니다.
- 선택한 인물의 부모·자녀 관계를 필터링해 볼 수 있습니다.
- 관계 후보에 `confirmed`, `needs_review`, `rejected` 상태를 사용합니다.
- 관계 목록의 인물 번호는 왼쪽 이미지에 표시된 번호와 동일합니다.

### 전통 족보 이름 및 배우자 처리

- 이름 앞의 `子`와 `女`는 이름 자체에서 분리해 성별 표식으로 저장합니다.
- OCR 원문에는 `子` / `女`가 포함된 원문 이름을 그대로 보관합니다.
- 부인은 여러 명 등록할 수 있습니다.
- 첩도 별도 유형으로 여러 명 등록할 수 있습니다.
- 배우자별 이름/본관/원문과 비고, 검수 상태를 보관합니다.

## 3. 설치

### 3.1 권장 환경

- Linux 또는 WSL2 Ubuntu 권장
- Python 3.12 권장 (기본 코드 문법은 Python 3.10 이상 기준)
- CPU 실행 가능
- PaddleOCR CPU 실행에는 충분한 메모리와 저장 공간이 필요합니다.

프로젝트 파일을 원하는 작업 디렉터리에 압축 해제하고 해당 폴더로 이동합니다.

```bash
cd /path/to/the-doos
```

### 3.2 공통 Python 패키지

```bash
python3.12 -m venv .venv-paddle
source .venv-paddle/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

이미 동작하는 `.venv-paddle` 환경이 있다면 새 가상환경을 만들 필요는 없습니다.

### 3.3 PaddleOCR 3.x CPU 설치

먼저 PaddlePaddle CPU 패키지를 설치한 뒤 PaddleOCR 패키지를 설치합니다.

```bash
python -m pip install paddlepaddle \
  -i https://www.paddlepaddle.org.cn/packages/stable/cpu/

pip install -r requirements-paddle.txt
```

설치 확인:

```bash
python - <<'PY'
import paddle
import paddleocr
print("PaddlePaddle:", paddle.__version__)
print("PaddleOCR:", paddleocr.__version__)
print("CUDA available:", paddle.is_compiled_with_cuda())
PY
```

프로젝트의 PaddleOCR 기본 설정은 `PP-OCRv5`, `chinese_cht`(번체 중국어), `cpu`입니다.

> **oneDNN 주의:** 이전 PaddlePaddle 환경에서 `ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]` 오류가 발생한 적이 있습니다. 현재 코드는 oneDNN을 기본적으로 비활성화합니다. 정상 실행을 확인하기 전에는 `--paddle-enable-mkldnn` 옵션을 추가하지 마세요. 이 옵션은 CPU oneDNN 가속을 명시적으로 켜는 용도입니다.

GPU를 사용하려면 시스템 CUDA 환경과 호환되는 PaddlePaddle GPU 패키지를 별도로 설치하고 `--paddle-device gpu:0`을 지정해야 합니다. CPU용 설치 명령과 GPU용 설치 명령을 혼용하지 마세요.

### 3.4 데스크톱 검수 UI 패키지 설치

```bash
pip install -r requirements-desktop.txt
```

이 파일은 공통 패키지, PySide6, 음력 날짜 변환용 `sxtwl`을 설치합니다. 그래픽 데스크톱 환경이 필요합니다. 선택 영역 OCR을 사용하려면 3.3절의 PaddleOCR도 설치해야 합니다.

## 4. OCR 실행

프로젝트 폴더에서 `jokbo_ocr.py`를 실행합니다.

### 4.1 PaddleOCR 실행

이미지 한 장:

```bash
python jokbo_ocr.py ./scan/001.jpg \
  --paddle-version PP-OCRv5 \
  --paddle-lang chinese_cht \
  --paddle-device cpu \
  --rows 6 \
  --output output/
```

폴더 안의 모든 지원 이미지:

```bash
python jokbo_ocr.py ./scan/ \
  --paddle-version PP-OCRv5 \
  --paddle-lang chinese_cht \
  --paddle-device cpu \
  --rows 6 \
  --output output/
```

연속된 일부 페이지만 실행하려면 Bash/WSL의 중괄호 범위 확장을 사용할 수 있습니다. 다음 명령은 `scan/genealogy/003.jpg`부터 `010.jpg`까지 8장을 처리합니다.

```bash
python jokbo_ocr.py ./scan/genealogy/{003..010}.jpg \
  --paddle-version PP-OCRv5 \
  --paddle-lang chinese_cht \
  --paddle-device cpu \
  --rows 6 \
  --output output/genealogy-003-010/
```

`{003..010}`은 셸에서 여덟 개의 파일 경로로 확장되고, `jokbo_ocr.py`의 `inputs` 인자는 여러 경로를 한 번에 받습니다. 기존 OCR 결과의 통합 JSON을 덮어쓰지 않도록 작업 범위마다 별도 출력 폴더를 사용하는 편이 안전합니다. Windows PowerShell에서는 중괄호 범위가 같은 방식으로 확장되지 않으므로 WSL/Bash에서 실행하거나 파일 경로를 각각 나열하세요.

PaddleOCR 결과는 지정한 출력 디렉터리에 바로 저장됩니다. 기존 `ocr_results.json` 형식과 `ocr_engine: "paddleocr"` 값은 유지합니다.

### 4.2 주요 명령줄 옵션

전체 옵션은 다음 명령으로 확인합니다.

```bash
python jokbo_ocr.py --help
```

자주 쓰는 옵션:

| 옵션 | 기본값 | 설명 |
|---|---:|---|
| `inputs` | 필수 | 이미지 파일 또는 이미지 디렉터리. 여러 경로 지정 가능 |
| `--output`, `-o` | `jokbo-output` | OCR 결과를 저장할 디렉터리 |
| `--paddle-lang` | `chinese_cht` | PaddleOCR 언어 코드 |
| `--paddle-version` | `PP-OCRv5` | `PP-OCRv5` 또는 `PP-OCRv4` |
| `--paddle-device` | `cpu` | 예: `cpu`, `gpu:0` |
| `--paddle-cpu-threads` | `4` | Paddle CPU 추론 스레드 수 |
| `--paddle-name-min-confidence` | `70` | 행 OCR 인명 결과 재사용 및 추가 OCR 중단 기준 |
| `--paddle-enable-mkldnn` | 꺼짐 | oneDNN CPU 가속을 명시적으로 활성화 |
| `--rows` | `6` | 예상 가로 행/구획 수 |
| `--scale` | `3.0` | OCR 이미지 확대 배율 |
| `--preprocess` | `clahe` | `clahe`, `gray`, `adaptive`, `otsu` |
| `--roi` | 자동 검출 | 수동 표 영역 `x,y,width,height` 지정 |
| `--no-auto-roi` | 꺼짐 | 표 외곽 자동 검출 비활성화 |
| `--column-ink-ratio` | `0.08` | 세로 열 검출 임계값 |
| `--min-column-width` | `5` | 세로 열 최소 폭(px) |
| `--person-min-component-width` | `18` | 인명 영역 검출용 큰 글자 구성요소 최소 폭 |
| `--person-min-component-height` | `18` | 인명 영역 검출용 큰 글자 구성요소 최소 높이 |
| `--person-min-component-area` | `100` | 인명 영역 검출용 최소 잉크 면적 |
| `--person-x-cluster-tolerance` | `8.0` | 인명 글자 x좌표 군집 허용 범위 |
| `--person-right-margin-exclusion` | `45` | 오른쪽 반복 책 제목 영역 제외 폭 |
| `--person-min-vertical-glyph-gap` | `27` | 이름 글자 사이 최소 세로 간격 |
| `--name-crop-padding` | `7` | 인명 crop 주위 여백(px) |

참고: `--min-name-font-ratio`는 하위 호환을 위해 남아 있는 deprecated 옵션입니다. 현재 인명 후보는 주로 이미지 기하 정보를 이용해 검출합니다.

## 5. OCR 결과 파일

OCR 실행 결과의 기본 구조:

```text
output/
├── ocr_results.json
├── people_candidates.json
├── people_candidates.csv
├── relationship_candidates.json
├── relationship_candidates.csv
├── rule_mentions.json
├── paddleocr_metrics_pages.csv       # PaddleOCR 실행 시
└── 001/                              # 원본 파일 stem별 페이지 폴더
    ├── table_roi.jpg
    ├── layout_debug.jpg
    ├── ocr.txt
    ├── rows.json
    ├── people_candidates.json
    ├── relationship_candidates.json
    ├── rows/
    └── columns/
```

주요 파일:

| 파일 | 설명 |
|---|---|
| `ocr_results.json` | 페이지별 행, 열, OCR 결과, 원본 이미지/페이지 처리 정보 |
| `people_candidates.json` | 페이지에서 검출한 인물 후보와 OCR 이름 후보, bbox, confidence, crop 경로 |
| `people_candidates.csv` | 인물 후보의 주요 필드를 표 형식으로 저장 |
| `relationship_candidates.json` | 기하 규칙으로 생성한 부모·자녀 관계 후보 |
| `relationship_candidates.csv` | 관계 후보를 표 형식으로 저장 |
| `rule_mentions.json` | 행 OCR에서 추출한 족보 관련 표식 및 규칙 언급 |
| `paddleocr_metrics_pages.csv` | PaddleOCR 페이지별 추론 횟수와 처리 시간 |
| `table_roi.jpg` | 검출된 족보 표 영역 이미지 |
| `layout_debug.jpg` | 행/레이아웃/인명 후보 검출 결과를 확인하기 위한 디버그 이미지 |
| `ocr.txt` | 페이지의 OCR 텍스트를 읽기 쉬운 형태로 모은 파일 |
| `rows.json` | 행별 텍스트와 세로 열 OCR 결과, 좌표 등 |
| `rows/`, `columns/` | 분할된 행 및 세로 열 이미지 |

인물 후보에는 보통 다음 정보가 포함됩니다.

- `person_id`: 페이지 내 OCR 후보 ID (예: `001_P0001`). 영구 인물 ID가 아닙니다.
- `name_hanja_candidate`: OCR 기반 이름 후보
- `raw_name_ocr`: 원본 OCR 이름 문자열
- `ocr_variants`, `ranked_ocr_hypotheses`: OCR 전처리/모델별 후보 결과
- `ocr_confidence`: OCR 엔진의 confidence 점수
- `bbox`: 원본 페이지 기준 인명 영역 좌표
- `image_file`: 인명 crop 이미지 경로
- `source_row_id`, `source_column_id`: 해당 인물이 발견된 행/열 ID
- `review_status`: 기본적으로 `needs_review`

`person_id`는 현재 OCR 결과 안에서 후보를 가리키는 로컬 식별자입니다. 여러 판본에 걸쳐 사용할 인물 ID는 검수 UI에서 생성하는 `person_uid`를 사용합니다.

## 6. 검수 UI 실행과 사용법

### 6.1 데스크톱 앱 실행

그래픽 데스크톱 환경에서 실행합니다.

```bash
python desktop_review.py output/
```

폴더 인자를 생략하면 창에서 OCR 결과 폴더를 선택합니다. 왼쪽 검수 영역은 현재 검수 페이지와 직전 페이지를 나란히 표시합니다. 예를 들어 002쪽을 고르면 왼쪽에 002쪽, 오른쪽에 001쪽이 표시되고, 다음 페이지를 고르면 003쪽과 002쪽이 표시됩니다. 오른쪽 페이지의 인물을 클릭하면 `이어진 기록` 탭의 연결 대상으로 지정할 수 있습니다. 첫 페이지는 직전 페이지가 없으므로 왼쪽에만 표시됩니다. 각 스캔에서 인물을 클릭하고 드래그로 이동합니다. `+`/`−`는 두 이미지를 함께 확대·축소하고 `Ctrl+휠`은 마우스가 놓인 이미지만 확대·축소합니다. 오른쪽에서 인물 정보와 검수 상태를 저장하거나 관계 후보를 승인·거절하고, 부모를 지정한 뒤 자녀들을 연결할 수 있습니다. OCR 항목을 선택하고 박스에 마우스를 올리면 원문이 이미지 위에 표시됩니다. `배우자 원문 (검수 초안)`에는 OCR로 읽은 문구가 표시되고, 배우자는 별도의 JSON 배열에서 여러 항목으로 편집합니다. 기존 항목의 유형과 나머지 속성을 유지해야 합니다.

확대·축소와 화면 맞춤 버튼은 **원본 이미지 바로 위**에 있고, 현재 쪽과 직전 쪽의 화면 확대율을 각각 표시합니다. `OCR 강조`는 전체 기록/이름/출생/관직 등을 고정 버튼으로 선택하므로 펼침 목록이 화면을 가리지 않습니다.

이미지에서 글자를 다시 읽으려면 `OCR 영역 드래그`를 누르고 현재 쪽 또는 직전 쪽에서 사각형을 드래그합니다. 이때 검수 박스가 자동으로 숨겨지며 `검수 박스 숨기기`로 별도 전환할 수도 있습니다. 오른쪽 `선택 영역 OCR` 탭에서 `선택 영역 OCR 실행`을 누르면 해당 부분만 백그라운드에서 인식하고 한자 후보·점수·전처리 방식을 목록에 표시합니다. 후보를 선택해 `선택한 한자 후보 복사`를 누르거나 후보를 더블클릭하면 한자만 클립보드에 복사되므로 원하는 필드에 붙여넣을 수 있습니다. 후보 생성과 복사는 원본 OCR이나 검수 상태를 변경하지 않습니다. 첫 실행은 OCR 모델 초기화 때문에 시간이 걸릴 수 있습니다.

화면을 크게 확대하면 검수 앱은 원본 이미지를 Lanczos 방식으로 화면 표시용으로 다시 계산해 글자 획이 덜 흐리게 보이도록 합니다. 좌표와 OCR 입력은 그대로 유지합니다. 선택 영역 OCR은 화면에 보이는 확대 이미지를 사용하지 않고, 선택 좌표로 원본 이미지(원본이 없을 때는 저장된 ROI)에서 해당 부분을 잘라 사용합니다. 기존 OCR 함수가 이 영역을 3배로 확대하고 대비·이진화 변형을 시험합니다. 픽셀 확대만으로 새로운 글자 정보가 생기지는 않으며 인식 결과는 원본 해상도와 인쇄 상태에 좌우됩니다.

페이지·인물·성별·검수 상태·기록 행·연결 대상의 목록은 항목을 선택하면 바로 닫힙니다.

출생·사망 원문에 왕/연호와 음력 연·월·일이 명확하면 `양력 출생`·`양력 사망`에 미검수 양력 초안이 표시됩니다. `연호·음력 변환…`을 누르면 나라(고려·조선·송), 왕/연호, 재위 연수, 음력 월·일과 윤달을 확인하는 창이 열립니다. 선택한 왕/연호의 서기 대응 연도가 즉시 표시됩니다. 목록에 보이는 `원년`은 그 왕의 **즉위 연도와 다를 수 있습니다**. 목록에 없는 왕/연호는 이름과 **원년의 서기 연도 및 마지막 서기 연도**를 직접 입력할 수 있습니다. 원문과 계산 결과를 대조했다면 창에서 확인 상태를 표시한 뒤 인물 저장을 누르세요. 원문을 바꾸면 이전 변환값은 다시 계산하거나 해제합니다.

출생·사망 아래의 `날짜 항목`에는 OCR에서 읽은 나라, 왕/연호, 재위 연수, 60갑자 연도, 음력 월·일을 **각각** 검토 대기 초안으로 표시합니다. 왕년으로 서기 연도를 확정할 수 있으면 대응 서기도 제안합니다. 예를 들어 OCR에 간지 첫 글자 `乙`만 있고 해당 왕년이 `乙巳`라면 60갑자 항목에는 `乙巳`를 제안하되, `OCR 간지 근거`에는 실제 판독 `乙`와 보완 사실을 따로 표시합니다. 원문과 대조한 후 항목을 고치거나 날짜 항목 확인을 선택하세요. 사망처럼 간지·월·일은 있어도 왕년이 없으면 해당 항목만 채우고 양력 변환은 보류합니다.

인명 누락이 보이면 `누락 인명 후보 찾기`를 누릅니다. 현재 페이지의 큰 글자 영역을 재검출하고 기존 OCR 열 텍스트를 참고해 **검토 대기** 후보를 추가합니다. 새 OCR 모델 추론은 실행하지 않습니다. 기존 후보 번호와 UUID는 유지하고, 추가 후보는 뒤에 붙입니다. 후보의 이름이 비어 있거나 잘못 읽혔다면 원본과 대조해 정정하세요. 이 기능은 기존 OCR 후보 파일을 다시 쓰지 않으며 새 후보는 검수 상태에 저장합니다.

페이지를 넘어 이어지는 기록은 다음 순서로 연결합니다.

1. 현재 페이지에 빠진 이름이 없는지 먼저 확인합니다. 같은 행에 새 인물이 있으면 이름 오른쪽의 이전 인물 계속 기록만 연결해야 합니다.
2. OCR 결과 폴더를 열면 통합 결과와 같은 폴더의 `001/rows.json` 같은 개별 페이지 결과를 자동으로 검색해 페이지 순서대로 목록에 넣습니다. 원본 스캔은 통합 결과에 기록된 스캔 폴더에서 같은 이름으로 찾습니다. 새 결과를 생성했다면 `페이지 다시 검색`을 누릅니다. 찾지 못한 페이지의 이유는 상태 표시줄에 나타나며 기존 OCR·검수 파일은 검색 중 변경하지 않습니다.
3. `이어진 기록` 탭에서 행을 고릅니다. 같은 위치에 연달아 있는 미배정 OCR 열은 한 영역으로 묶여 위치 좌표와 원문 앞부분이 목록에 표시됩니다. 영역을 선택하면 오른쪽에 전체 OCR이 나오고 왼쪽 이미지에 그 영역의 박스가 표시됩니다. 연결할 영역을 체크하세요.
4. 같은 행의 이전 페이지 인물을 선택하고 `선택한 OCR 영역을 인물에 연결`을 누릅니다. 오른쪽에서 왼쪽으로 읽는 순서의 마지막 인물을 먼저 제안하지만, 최종 연결은 검수자가 판단합니다. 숫자 페이지가 건너뛰어 있으면 이전 페이지 결과가 있어야 합니다.
5. 원래 인물 페이지에서 연결 기록의 관직·생몰·묘소·배우자 등 분류 초안을 확인합니다. 해당 입력란에는 연결된 문구가 이어 붙은 상태로 나타나며, 표식이 없는 문장은 `인물 기록`에 나타납니다. 원본 이미지와 대조해 수정한 뒤 인물 정보를 저장하세요. 잘못 연결했다면 원문 페이지의 `이어진 기록`에서 저장된 연결을 선택해 해제할 수 있습니다.

기록만 이어지는 페이지가 여러 장이면 앞 페이지의 확정된 기록 연결을 따라 원래 인물을 제안합니다. 원문 글자나 페이지 배치만으로 동일인을 자동 병합하지 않습니다. 인접 열 묶음은 검수를 돕는 화면 단위이며, 저장할 때는 원래 열별 OCR·좌표·토큰 근거를 유지합니다. 자동으로 찾은 영역에는 잡음이나 누락된 새 이름이 섞일 수 있으므로 연결 전에 꼭 확인하세요.

오른쪽의 인물 목록에서 이름 또는 ID로 검색하고 검수 상태와 완료 수를 확인할 수 있습니다. 앱에 포함된 Noto Sans CJK KR 글꼴을 사용하므로 시스템에 한글·한자 글꼴이 없어도 표시할 수 있습니다. 글꼴 및 라이선스는 `assets/fonts/`에 있습니다. 표시되지 않는 희귀 한자가 있다면 해당 글리프를 포함한 추가 시스템 글꼴이 필요할 수 있습니다.

`원문 자녀 표식`의 `子`와 `女`는 OCR 원문에 적힌 표식이고, `성별`은 별도로 검수하는 값입니다. 기존 성별 값이 없을 때만 표식으로 초기 선택을 제안하며, 모르면 `미상`을 선택합니다. 두 값이 서로 달라도 원문 표식을 자동 수정하지 않습니다. 기존 검수 파일과 내보내기에는 각각 `sex_marker`와 `gender`로 기록합니다.

한글 입력과 한자 변환은 운영체제 입력기를 사용합니다. Linux에서는 예를 들어 IBus와 한국어 입력기(`ibus-hangul`)를 설치하고 데스크톱 설정에서 한국어 입력 소스를 추가한 뒤 앱을 다시 실행하세요. 설치 후에도 입력이 안 되면 다른 앱에서 한글 입력이 되는지와 `XMODIFIERS`, `QT_IM_MODULE` 입력기 설정을 확인하세요. 입력기와 한자 변환 단축키는 데스크톱 환경에 따라 다릅니다. 앱은 OpenCV가 Qt 입력기 플러그인 경로를 덮어쓰는 문제를 방지하지만, 시스템 입력기를 대신 설치하지는 않습니다.

### 6.2 검수·저장

오른쪽의 `인물 검수` 탭에서 OCR 원문과 필드별 근거를 확인하고 값을 수정한 뒤 `인물 저장`을 누릅니다. 관계 탭에서 후보를 승인·거절하거나 부모를 지정하고 자녀를 추가할 수 있습니다. `이어진 기록` 탭에서는 이전 페이지 인물에게 연결할 OCR 영역을 검토합니다. 선택 영역 OCR 후보는 복사하여 원하는 필드에 붙여넣을 수 있습니다.

저장 시 기존 `review_state.json` 형식과 JSON/CSV 내보내기를 사용합니다. 저장 전에 외부 검수 상태 변경을 감지하므로 충돌 시 폴더를 다시 열어야 합니다. 데스크톱에서 생성한 UID는 검수 상태와 내보내기에 저장되며 공용 `person_registry.json`은 자동 변경하지 않습니다.

현재 데스크톱 앱에는 판본 메타데이터 편집, 공용 레지스트리 갱신·기존 UID 연결, 관계 후보의 부모/자녀 교체와 관계 되돌리기 기능이 없습니다. 이러한 작업이 필요하면 저장된 JSON을 백업하고 별도 도구로 검토해야 합니다.

## 7. 인물 정보 자동 추출

인물을 선택하면 저장된 세로 열 OCR 결과와 bbox를 이용해 인물 정보 초안을 자동으로 추출하고 입력 필드에 미리 채웁니다. **새 OCR 추론은 실행하지 않습니다.** 원본 OCR 결과를 재사용하며, 직접 수정한 값이나 이미 저장한 검수 값이 자동 초안보다 우선합니다.

### 7.1 인물 기록 영역 분리

전통 족보에서는 인물 이름이 기록 블록의 오른쪽 가장자리에 위치하는 형태가 많다는 점을 이용합니다. 같은 행에서 해당 인물 이름 열과 다음 인물 이름 열 사이의 OCR 세로 열을 해당 인물의 기록 영역으로 추정합니다.

### 7.2 키워드 기반 필드 초안

| 필드 | 검색하는 대표 표식/키워드 |
|---|---|
| 출생 | `生`, `誕生`, `降生` |
| 사망 | `卒`, `薨`, `歿`, `殁`, `終`, `逝世` |
| 관직 | `官至`, `進士`, `登科`, `中書`, `舍人`, `侍郎`, `刺史`, `尚書` 등 |
| 배우자 | `配`, `夫人`, `淑夫人`, `宜人`, `貞夫人`, `妾`, `媵`, `側室` 등 |
| 묘소 | `葬`, `墓`, `墳`, `壙`, `坐之原`, `同原`, `設壇` 등 |
| 자(字) | `字` |
| 호(號) | `號`, `号` |

키워드와 열의 순서를 이용해 초안을 제시합니다. 배우자 표식 뒤의 열은 배우자 기록으로 분리하고, 출생·사망·관직·묘소는 각 표식의 경계에서 잘라 인접 필드의 열이 섞이지 않도록 합니다. 한 열에 사망과 매장 기록이 함께 있으면 초안 텍스트는 나누되 실제 근거 bbox는 공유합니다. `因號`처럼 지명 유래를 설명하는 문구는 인물의 호로 자동 입력하지 않습니다. 이미지 영역, OCR 텍스트, 열 bbox 등 근거를 화면에서 확인할 수 있습니다.

확정 연결한 다른 페이지의 기록도 같은 규칙으로 분류합니다. 연결된 부분의 관직·출생·사망·묘소·배우자·자·호 문구는 해당 필드의 미검수 초안으로 이어 붙여 표시하고, 전체 원문은 `인물 기록`에도 추가로 보여 줍니다. 여러 배우자 가능성을 고려해 새 배우자 문구는 유형 미확정인 별도 검수 항목으로 제안합니다. 연결을 해제하면 아직 저장하지 않은 제안은 사라집니다.

### 7.3 자동 추출의 한계

이 필드 추출은 **레이아웃과 키워드에 근거한 초안 생성**입니다. 문장 의미를 완전히 이해하지 못하고 주변 텍스트가 인접한 다른 인물 또는 배우자 기록일 수도 있습니다. 별도 양력 변환은 식별 가능한 날짜 표기만 처리하며 인물 소유를 판단하지 않습니다. 따라서 자동 입력한 모든 값은 원본 이미지와 대조해야 합니다. 비어 있는 값을 임의로 추측해 채우지 않습니다.

## 8. 데이터 모델: 원본·검수·고유 ID

### 8.1 Raw Data와 Reviewed Data 분리

인물 내보내기 레코드에는 OCR에서 나온 원본 데이터와 검수자가 정리한 데이터를 함께 보관합니다.

**`raw_data` — 원본 OCR 및 근거**

- `image`: 원본 이미지 경로, 인명 crop 경로, bbox
- `name_ocr`: 이름 OCR 원문, 정규화 후보, `子`/`女` 표식, confidence, bbox, OCR 대안 가설
- `record_ocr`: 해당 인물에게 배정한 OCR 기록 전체, 행/열 ID, 추출 방식
- `field_ocr`: 출생/사망/관직/배우자/묘소/자/호 관련 OCR 원문과 근거 열 및 bbox
- `source_occurrence`: 판본과 스캔 위치 정보

**`reviewed_data` — 사람이 검수한 정보**

- `name_hanja`: 검수한 이름 (앞의 `子` / `女` 표식 제외)
- `sex_marker`, `gender`: 족보 표식 및 성별 정보
- `generation_number`: 세대
- `courtesy_name_hanja`, `pen_name_hanja`: 자와 호
- `birth_text`, `death_text`: 출생 및 사망 원문/정리 내용
- `birth_date`, `death_date`: 분리된 날짜 항목. `country`(예: 고려), `ruler_or_era`(왕 또는 연호), `regnal_year`, `ce_year`, `sexagenary_year`, `month`, `day`, `leap_month`를 담습니다. `sexagenary_ocr`는 **실제로 판독된 간지 문자열**, `sexagenary_source`는 OCR 그대로인지 왕년에서 보완했는지 나타냅니다. `source_text`, `review_status`, `year_conflict`, `ambiguous`로 근거와 미해결 충돌을 기록합니다. 읽히지 않은 월·일은 `null`입니다.
- `birth_solar`, `death_solar`: 양력 변환 결과(없으면 `null`). `start`/`end`는 **양끝 포함** ISO 날짜, `precision`은 `day`/`month`/`year`, `lunar`는 원래 음력 연·월·일·윤달, `reference`는 나라·왕/연호·재위 연수와 대응 연도 근거, `source_text`는 변환 당시 원문, `calendar_model`은 계산 모델, `review_status`는 날짜 자체의 검토 상태입니다. OCR 원문은 이 객체로 대체하지 않습니다.
- `office_title`: 관직·품계·봉호
- `spouses`: 여러 부인/첩/기타 배우자 배열
- `burial_text`: 묘소·장지
- `biography_text`: 인물 기록
- `notes`: 검수 메모
- `review_status`: 인명 검수 상태
- `information_review_status`: 추가 정보 검수 상태

날짜 변환은 `historical_dates.py`와 `sxtwl==2.0.7`을 사용합니다. 서기 날짜는 **역산 그레고리력**으로 표시하며, `sxtwl`의 중국 천문 역법 모델을 사용하므로 시대·지역에 따라 실제 고려/조선의 역일과 다를 가능성을 검수해야 합니다. 고려 왕 원년은 [국사편찬위원회 『고려사절요』 목차](https://db.history.go.kr/goryeo/compareViewer.do?levelId=kj_%24s04), 조선 왕대는 [국사편찬위원회 조선왕조실록](https://sillok.history.go.kr/main.do), 개보·순화 대응 연도는 [국사편찬위원회 사료](https://db.history.go.kr/id/sy_002r_0010_0190_0060)를 참고했습니다. `sxtwl` 날짜는 [『고려사』 975년 음력 10월 26일](https://db.history.go.kr/goryeo/itemLevelKrList.do?itemId=&levelType=&parentId=kr_002r_0570_0010&types=r)과 [1048년 음력 정월 초하루](https://db.history.go.kr/goryeo/itemLevelKrList.do?itemId=kr&parentId=kr_007r_0040_0010&types=r)의 양력 날짜와 대조했습니다. 왕/연호 목록은 검증된 항목만 제공하며 전체 연호 목록은 아닙니다.

원본 이미지 바이너리를 JSON 안에 넣지는 않습니다. 경로와 bbox로 참조합니다. 이미지 파일을 이동하거나 다른 컴퓨터에서 검수할 때는 `source_image`와 `image_file` 경로가 유효하도록 유지해야 합니다.

### 8.2 `子` / `女` 표식 보존

이름의 첫 글자가 `子` 또는 `女`이면 이름 후보에서 해당 글자를 분리합니다.

| OCR 원문 | 이름 후보 | 보관하는 표식 |
|---|---|---|
| `子之建` | `之建` | `sex_marker=子`, `gender=male` |
| `女明玉` | `明玉` | `sex_marker=女`, `gender=female` |
| `杜慶寧` | `杜慶寧` | 표식 없음 |

`raw_data.name_ocr.raw_text`에는 원문 값이 남습니다. 이 규칙은 이름 맨 앞의 글자만 대상으로 합니다.

### 8.3 영구 인물 ID와 판본별 출처

인물의 고유 ID는 다음과 같은 UUID 기반 opaque key입니다.

```text
PER_<UUID>
예: PER_79F2B15A...
```

쪽수·열 번호·스캔 파일명을 영구 인물 ID로 사용하지 않는 이유는 개정판에서 같은 인물의 위치가 달라질 수 있기 때문입니다. 위치는 인물의 정체성이 아니라 **어떤 판본의 어디에서 발견되었는지**를 나타내는 출처 정보입니다.

다음 데이터는 `source_occurrence`에 별도로 보관합니다.

- `source_occurrence_id`
- `edition_id`, `publication_year`, `volume`
- `printed_page`, `scan_page`, `source_image`
- `source_row_id`, `row_number`
- `source_column_id`, `column_number_right_to_left`
- `position_in_column`
- `bbox`

현재 첫 번째 OCR 검수에서는 각 OCR 인물 후보에 `PER_<UUID>`를 한 번 발급하고, `review_state.json`의 `person_uid_map`에 저장해 같은 OCR 등장 위치의 ID를 유지합니다. 이 매핑을 찾는 내부 occurrence key에는 판본/페이지/행/열/bbox 정보가 사용됩니다. 즉 **UUID 값 자체가 위치에서 계산되는 것은 아니지만**, 최초 OCR 등장 항목을 다시 찾기 위해 위치를 사용합니다.

### 8.4 개정판과 공용 인물 레지스트리

데스크톱 앱은 기존 `review_state.json`의 `person_uid_map`, 판본 메타데이터와 출처 정보를 읽고 보존합니다. 기본 판본 메타데이터는 `edition_id=jokbo-1987`, `publication_year=1987`입니다. 현재 화면에서는 판본 정보 수정, 공용 `person_registry.json` 갱신, 개정판의 동일인 UID 선택을 지원하지 않습니다. 서로 다른 판본의 동명이인을 자동 병합하지 않으며, 판본 간 동일인 연결에는 별도 검수 기능이 필요합니다.

### 8.5 권장 데이터베이스 구조

프로젝트 자체는 DB에 직접 저장하지 않고 JSON/CSV를 내보냅니다. 향후 DB로 옮길 때는 아래처럼 정규화하는 방식을 권장합니다.

**Person**

- `person_uid` — Primary Key
- 검수된 이름, 성별 표식, 생몰, 관직, 자/호, 메모 등

**PersonSourceOccurrence**

- `source_occurrence_id` — Primary Key
- `person_uid` — Person Foreign Key
- 판본/연도/권/인쇄 쪽수/스캔 파일/행/열/열 내 순번/bbox
- 원본 OCR 및 이미지 참조

**ParentChildRelationship**

- 관계 식별자
- `parent_person_uid` — Person Foreign Key
- `child_person_uid` — Person Foreign Key
- `review_status`, 관계 근거, 출처

**PersonSpouse / SpouseRecord** (DB 구현 시 선택)

- 한 인물에게 여러 배우자 기록을 연결
- 부인/첩/기타 유형, 원문, 검수 상태 저장

부모 한 명과 자녀 여러 명은 여러 `ParentChildRelationship` 레코드로 나타냅니다. 예를 들어 `A→B`, `A→C`, `A→D`는 각각 별도 행입니다.

### 8.6 페이지를 넘어 이어지는 원문 기록

선택한 OCR 열은 `review_state.json`의 `continuation_links`에 원문 페이지·행, 전체 OCR 텍스트, 열 ID·bbox·token bbox·confidence, 연결 대상 `person_uid`와 검수 상태를 함께 저장합니다. 새 이름이 있는 행에서도 그 이름보다 오른쪽의 미배정 열을 별도로 연결할 수 있습니다. 연결 해제는 `rejected`로 남기고 확정된 링크만 내보냅니다.

인물 내보내기에는 `raw_data.record_ocr.continuations`와 추가 `source_occurrences`(`occurrence_type=record_continuation`)로 보존합니다. 분류된 연결 원문은 `raw_data.field_ocr.<필드>.continuations`에도 원본 페이지·행·열 bbox와 함께 기록합니다. 다른 페이지의 좌표를 원래 페이지 위에 그리지 않습니다. 기존 검수 값 뒤에 미검수 초안을 표시하며, 인물 저장 전에 원본과 대조해야 합니다. 새 연결이 생기면 추가 정보 검수 완료 표시는 다시 확인이 필요한 상태로 보이고, 검수자가 입력란에서 제안 문구를 지워 저장하면 그 문구를 다시 제안하지 않습니다. 이미 저장한 검수 문구는 연결 해제만으로 지우지 않으므로 해제 후 해당 필드도 확인하세요.

명시적으로 불러온 개별 페이지 결과는 `supplemental_pages`, 재검출한 미검수 인명은 `additional_people`에 추가 저장합니다. 두 UI의 저장·내보내기는 이 확장 항목을 보존하며 기존 검수 상태도 계속 읽습니다. 원본 OCR을 나중에 다시 생성하면 추가 후보와 중복되는지 검토해야 하며 이름만으로 자동 병합하지 않습니다.

## 9. 부모·자녀 관계 추출 규칙

관계 자동 추출은 사용자가 설명한 족보의 판면 배치 원칙을 코드화한 기하 규칙입니다. 세대 숫자(`一世`, `二世` 등)는 부모·자녀 연결 판단에 사용하지 않습니다.

기본 규칙:

- **첫째 아들 후보**: 아버지 인물 바로 아래 행에서 x좌표가 거의 정렬되는 인물
- **둘째 아들 이후 후보**: 첫째 아들보다 왼쪽에 있는 인물. 위치에 따라 자녀 순서를 추정
- **딸 후보**: 아들 후보들보다 오른쪽에 있는 인물
- **부모 후보가 여러 명인 행**: 인접 부모 x좌표 사이의 중간값으로 각 부모의 branch 구간을 분리
- 경계가 모호하거나 위치 규칙에 잘 맞지 않는 경우 경고와 함께 검토 후보로 남김

자동 생성 관계는 원칙적으로 `needs_review`입니다. 화면에서 사람이 직접 부모와 자녀를 연결하면 `confirmed`로 저장합니다.

> 이 규칙은 특정 족보의 판면 구조에 맞춰 만든 것입니다. 다른 문중·다른 판본에 그대로 적용할 때는 관계 후보를 다시 검수해야 합니다. 배치 위치는 실제 친자관계를 증명하지 않습니다.

## 10. 검수 결과 및 내보내기 파일

데스크톱 검수 앱에서 저장하면 OCR 결과 디렉터리에 다음 파일이 생성/갱신됩니다.

| 파일 | 내용 |
|---|---|
| `review_state.json` | 인물 수정 내용, 관계 수정/거절, 수동 관계, `person_uid_map`, 판본 및 페이지 메타데이터 |
| `reviewed_people.json` | OCR 원문, 검수 정보, `person_uid`, raw/reviewed data, 출처 정보가 포함된 인물 데이터 |
| `reviewed_people.csv` | 인물 데이터를 CSV로 내보냄. 중첩 구조는 JSON 문자열로 저장 |
| `reviewed_relationships.json` | 부모/자녀 로컬 후보 ID와 영구 `person_uid`를 함께 저장 |
| `reviewed_relationships.csv` | 관계 상태, 부모/자녀 이름과 `person_uid`를 저장 |

`review_state.json`과 기존 `person_registry.json`은 검수 작업을 이어가는 데 중요합니다. 주기적으로 백업하세요. 데스크톱 앱은 `person_registry.json`을 자동 갱신하지 않습니다.

## 11. 성능 확인

PaddleOCR 실행 결과의 `paddleocr_metrics_pages.csv`에는 다음 값이 들어갑니다.

| 필드 | 의미 |
|---|---|
| `source_page` | 원본 페이지 파일명 |
| `elapsed_seconds` | 페이지 처리 시간 |
| `row_inferences` | 행 OCR 추론 횟수 |
| `name_reused_from_row` | 행 OCR 결과를 재사용한 인명 수 |
| `name_fallback_regions` | 추가 crop OCR이 필요했던 인명 영역 수 |
| `name_fallback_inferences` | 인명 crop 추가 추론 횟수 |
| `total_inferences` | 행 OCR + 인명 fallback 추론 총 횟수 |

v5의 반복 crop OCR 구조와 v6 이후 최적화 구조를 비교할 때는 처리 시간뿐 아니라 `total_inferences`도 확인하세요. 첫 실행의 모델 다운로드/초기화 시간과 이후 캐시가 준비된 실행 시간은 구분해 측정하는 것이 좋습니다.

OCR confidence는 보정된 정확도 확률이 아닙니다. 검수한 정답 문자열을 기준으로 이름 완전 일치율과 문자 오류율(CER)을 평가하세요.

## 12. 테스트

프로젝트 디렉터리에서 실행합니다.

```bash
python -m unittest discover -s tests -v
```

현재 테스트는 다음 항목을 확인합니다.

- PaddleOCR 결과 구조와 bbox 좌표 변환
- 세로 열 순서(오른쪽에서 왼쪽) 및 텍스트/인명 bbox 매칭
- 행 OCR 재사용 및 staged crop fallback 중단 조건
- 인명 검출과 부모·자녀 배치 규칙
- 복수 부모 branch 구분
- 선택 인물의 부모/자녀 관계 필터링 및 이미지 번호 매핑
- `子` / `女` 이름 표식 분리
- 영구 UID 유지, 판본 출처 위치, 레지스트리 병합
- raw/reviewed data 분리
- 인물 정보 OCR 키워드 기반 초안 추출
- 이어진 기록의 부분 행·다중 페이지 연결, 원본 좌표/검수값 보존, 연결 해제와 이전 결과 복원
- 세로로 분리된 글자 획으로 인한 인명 검출 누락 및 기존 페이지 본문 오탐 방지

테스트는 단위 로직을 확인하며 실제 PaddleOCR 모델 추론이나 데스크톱 UI의 수동 조작 검증과는 다릅니다. OCR 엔진을 실제로 실행하는 검증은 사용자의 설치 환경에서 수행해야 합니다.

## 13. 문제 해결

### 13.1 `ConvertPirAttribute2RuntimeAttribute ... pir::ArrayAttribute` 오류

PaddlePaddle/PaddleOCR 조합에서 oneDNN/PIR 호환 문제가 발생한 경우입니다. 현재 코드에서는 oneDNN이 기본적으로 꺼져 있습니다. 명령줄에 `--paddle-enable-mkldnn`을 추가하지 말고 다시 실행합니다.

가상환경의 버전을 확인하려면:

```bash
python - <<'PY'
import paddle, paddleocr
print("PaddlePaddle:", paddle.__version__)
print("PaddleOCR:", paddleocr.__version__)
PY
```

### 13.2 검수 UI에서 OCR 결과를 찾지 못함

사이드바의 `OCR 결과 디렉터리`가 `ocr_results.json`이 있는 위치인지 확인합니다.

- 현재 실행: 보통 `output`
- 과거 비교 실행에서 저장된 PaddleOCR 결과: `output/paddleocr`

### 13.3 원본 이미지가 표시되지 않음

OCR 실행 당시의 원본 이미지 경로가 현재도 유효한지 확인합니다. 원본을 다른 곳으로 옮긴 경우 경로가 끊어질 수 있습니다. 원본 이미지를 찾을 수 없으면 검수 UI는 페이지 출력 폴더의 `table_roi.jpg`를 대체 이미지로 시도합니다. 원본 전체 페이지보다 표시 범위가 제한될 수 있습니다.

### 13.4 확대 이미지가 느리거나 화면이 무거움

높은 확대율에서는 이미지 렌더링과 메모리 사용량이 늘어납니다. 필요한 영역을 확인한 뒤 `화면 맞춤`으로 돌아오세요.

## 14. 현재 한계와 검수 원칙

1. **OCR confidence는 정답 확률이 아닙니다.** 높은 confidence도 오인식일 수 있습니다.
2. **자동 인명 후보는 누락되거나 잘못 검출될 수 있습니다.** 이미지와 후보 bbox를 함께 확인해야 합니다.
3. **인물 정보 자동 추출은 규칙 기반 초안입니다.** 기록 블록을 인접 열로 추정하고 키워드 주변 텍스트를 모으므로 다른 인물의 정보가 섞일 수 있습니다.
4. **자동 부모·자녀 관계는 판면 규칙의 추정 결과입니다.** 검수 전에는 확정 계보로 사용하지 마세요.
5. **배우자 유형은 원문 확인이 필요합니다.** 배우자 키워드가 검출되었다고 부인/첩 구분이 자동 확정되는 것은 아닙니다.
6. **개정판의 동일인 연결은 사람이 판단해야 합니다.** 이름이 같다는 이유로 `person_uid`를 자동 병합하지 않습니다.
7. **DB 저장은 아직 구현하지 않았습니다.** 현재는 검수된 JSON/CSV를 내보내며 공용 ID 레지스트리는 자동 갱신하지 않습니다.
8. **UI는 로컬 검수용입니다.** 검수 파일과 스캔의 접근 권한을 관리하세요.

족보에는 생존 인물이나 가족에 관한 정보가 포함될 수 있습니다. 원본 이미지와 검수 결과의 접근 권한을 관리하고 외부 공개 전에 자료 권리 및 개인정보 문제를 확인하세요.

## 15. 버전별 기능 이력

이 표는 별도 README 여러 개를 대체하는 통합 변경 이력입니다. 현재 사용 방법과 동작은 위의 각 기능 설명을 기준으로 합니다.

| 버전 | 주요 추가/변경 사항 |
|---|---|
| v2 | LLM에 의존하지 않는 OpenCV + Python 규칙 기반 처리의 초기 구조 |
| v3 | 이미지 기하 기반 인명 후보 검출 개선, 오탐 제거, 위치를 이용한 부모·자녀 후보 생성 |
| v4 | 인명 crop 전용 OCR, 여러 전처리/OCR 후보 보존, 복수 부모 branch 구분 및 관계 근거 기록 |
| v5 | 인명 OCR 후보 비교 및 OCR 결과 구조 확장 |
| v5 oneDNN 수정 | CPU PaddleOCR 실행 시 PIR/oneDNN 호환 오류를 피하도록 oneDNN 비활성화를 기본값으로 설정 |
| v6 | 행 OCR 결과를 인명 후보에 재사용해 중복 추론을 줄임 |
| v6.1 | 페이지 전체 보기, 이미지 조작/관계 취소 동작 및 검수 메시지 위치 개선 |
| v6.2 | 부모 한 명에게 여러 자녀를 연결하는 1:N 검수, 인물 정보 편집 기능 추가 |
| v6.3 | 부모 선택 시 기존 관계선 표시, 오른쪽 패널 독립 스크롤, 기존 OCR 텍스트 기반 인물 정보 초안 추출 |
| v6.4 | 선택 인물 관련 관계 필터, 이미지 번호와 관계 목록 번호 통일 |
| v6.5 | 무제한 최대값의 이미지 확대 배율, `子`/`女` 표식 분리, 복수 부인/첩, raw/reviewed 데이터 분리, 영구 인물 ID 및 판본 출처 정보, OCR bbox 강조 |
| v6.6 | 관계선과 UI 색상 개선, 부모 bbox 아래쪽에서 자녀 bbox 위쪽으로 연결, 인물 선택 시 OCR 정보 초안 자동 준비, 로컬 이미지 드래그 팬 뷰어 추가 |
| v6.7 | 검수 화면의 이미지 탐색과 인물별 OCR 근거 표시 개선 |
| v6.7.1 | 인물 미선택 상태의 첫 화면에서 OCR 강조 focus가 초기화되지 않아 발생하는 UnboundLocalError 수정, 오래된/잘못된 세션 값에 대한 안전한 기본값 및 회귀 테스트 추가 |
| 2026-11-10 | 검수 UI를 PySide6 데스크톱 앱으로 통일하고 웹 UI 의존성을 제거 |

## 16. 프로젝트 파일 구성

```text
the-doos/
├── README.md
├── jokbo_ocr.py                 # OCR, 레이아웃, 인명 및 관계 후보 처리
├── desktop_review.py           # PySide6 데스크톱 검수 UI
├── review_core.py              # 검수 상태 및 내보내기 공통 함수
├── review_helpers.py            # 관계 표시/필터 및 인물 번호 헬퍼
├── person_info_extractor.py     # 기존 OCR 열 기반 인물 정보 초안 추출
├── person_data_model.py         # Raw/Reviewed data, person_uid, source occurrence, registry
├── requirements.txt             # 공통 의존성
├── requirements-paddle.txt      # PaddleOCR 의존성
├── requirements-desktop.txt     # PySide6 검수 UI 의존성
├── .gitignore
└── tests/
    ├── test_paddle_adapter.py
    ├── test_paddle_optimization.py
    ├── test_person_data_model.py
    ├── test_person_info_extractor.py
    ├── test_relationship_layout.py
    └── test_review_helpers.py
```


## 17. 처음 참여하는 개발자를 위한 빠른 시작

이 저장소를 처음 보는 개발자나 Codex 에이전트는 **이 README를 먼저**, 코드 수정 전에 저장소 루트의 [AGENTS.md](AGENTS.md)를 읽습니다. `AGENT.md`는 `AGENTS.md`의 안내 파일입니다. 설계·사용법은 README, 작업 중 반드시 지킬 규칙은 AGENTS.md가 담당합니다.

### 17.1 현재 저장소의 성격과 범위

- 이 프로젝트는 **1987년 발행 족보**의 스캔본을 출발점으로, 판본이 달라져도 재사용할 수 있는 인물·가족관계·출처 데이터를 만드는 로컬 도구입니다.
- 입력 스캔은 저장소의 `scan/`에 있으며 `scan/001.jpg`는 작은 단위의 재현/확인에 적합합니다. `scan/`의 모든 파일을 테스트 목적으로 일괄 OCR하지 마세요.
- **아직 구현된 데이터베이스 서비스는 없습니다.** 현재 영속적인 결과는 JSON/CSV와 인물 ID 레지스트리이며, 향후 DB 테이블 구조는 8.5절의 제안입니다.
- 이 저장소는 OCR/검수 앱 외에 과거 실험 파일을 포함할 수 있습니다. 현재 실행 진입점은 `jokbo_ocr.py`와 `desktop_review.py`입니다.

### 17.2 첫 실행 순서

```bash
git clone https://github.com/myungcheol/the-doos.git
cd the-doos
python3.12 -m venv .venv-paddle
source .venv-paddle/bin/activate
python -m pip install -U pip
pip install -r requirements-desktop.txt
python -m unittest discover -s tests -v
python jokbo_ocr.py --help
```

- **OCR을 실제로 돌릴 때**만 3.3절의 PaddlePaddle/PaddleOCR 설치가 추가로 필요합니다. 모델 없이도 실행 가능한 단위 테스트와 OCR 추론 테스트를 혼동하지 마세요.
- OCR 실행 예시는 4절, 검수 UI는 6절을 따릅니다. 처음에는 `scan/001.jpg` **한 페이지만 별도 출력 폴더에** 실행해 보세요.
- 검수 UI에는 기존 OCR 결과 폴더(`ocr_results.json`이 있는 곳)를 지정합니다. **OCR 결과가 없는 새 clone 상태에서 UI만 실행해도 검수할 페이지는 없습니다.**
- 사용자 작업 디렉터리가 꼭 `~/workspaces/jokbo_ocr_project`일 필요는 없습니다. clone한 저장소 루트에서 명령을 실행합니다.

### 17.3 실제 작업을 시작할 때

1. `git status`와 `git log -5 --oneline`으로 현재 코드/미커밋 변경 사항을 확인합니다.
2. 문제를 재현하고 **19절의 변경 절차**를 따릅니다. UI 문제라면 `desktop_review.py`를, 검수 저장·내보내기 문제라면 `review_core.py`를 확인합니다.
3. 입력 스캔, OCR 원본과 `review_state.json`은 서로 다른 역할을 합니다. 실험 출력 디렉터리로 테스트하고 검수자의 기존 결과를 덮어쓰지 않습니다.
4. 작업 결과에는 변경 파일, 재현/테스트 결과, 실제로 실행하지 못한 테스트, 커밋 SHA를 구분해서 기록합니다.

## 18. 소스 코드와 데이터 찾아보기

### 18.1 요구사항별 수정 위치

| 찾고 싶은 것 / 하려는 일 | 우선 읽을 파일 |
|---|---|
| OCR 전체 처리 흐름, CLI 옵션, OpenCV 레이아웃·인명/관계 후보 생성 | `jokbo_ocr.py` |
| PaddleOCR 결과 어댑터, 행 OCR 재사용, 인명 crop fallback | `jokbo_ocr.py`, `tests/test_paddle_adapter.py`, `tests/test_paddle_optimization.py` |
| 부자관계 추론의 판면/기하 규칙 | `jokbo_ocr.py`, `tests/test_relationship_layout.py` |
| 인물 선택, 이미지 표시, 입력폼, 관계 검수 | `desktop_review.py`, `tests/test_desktop_review.py` |
| 검수 상태·내보내기·원본 이미지 로딩 | `review_core.py` |
| 이전 페이지 기록 연결·원문 근거, 개별 페이지 불러오기, 누락 인명 복구 | `review_extensions.py`, `tests/test_review_extensions.py` |
| 실제 줌/팬, 클릭, bbox·관계선의 화면 표시 | `desktop_review.py` |
| 관계 목록 번호/필터, 관계선 끝점, OCR focus 안전 처리 | `review_helpers.py`, `tests/test_review_helpers.py` |
| 인물별 출생·사망·관직·배우자·묘소 OCR 초안과 evidence bbox | `person_info_extractor.py`, `tests/test_person_info_extractor.py` |
| 왕/연호 연수와 음력→양력 범위 계산 | `historical_dates.py`, `tests/test_historical_dates.py` |
| `raw_data`/`reviewed_data`, `PER_<UUID>`, 판본 출처, 레지스트리 | `person_data_model.py`, `tests/test_person_data_model.py` |
| 데스크톱 검수 UI 실행/의존성 | `desktop_review.py`, `requirements-desktop.txt` |
| OCR 의존성 | `requirements-paddle.txt` |

`person_data_extractor.py`도 저장소에 남아 있습니다. **현재 검수 UI가 직접 import하는 모듈은 `person_info_extractor.py`**입니다. 유사한 파일명이 있다는 이유로 둘을 일괄 수정하거나 삭제하지 말고 실제 import와 사용 경로를 확인하세요.

### 18.2 데이터별 위치와 구분

| 구분 | 위치/예시 | 의미와 주의 |
|---|---|---|
| 원본 스캔 | `scan/001.jpg`, `scan/frontmatter/...` 등 | 손실 없는 입력 원본. 임의로 덮어쓰지 않음 |
| OCR/추론 원본 | `output/ocr_results.json`, `people_candidates.json`, `relationship_candidates.json` | 재생성 가능한 후보 데이터. 검수자가 직접 수정하는 저장소가 아님 |
| OCR 좌표/이미지 | `output/001/rows.json`, `table_roi.jpg`, `layout_debug.jpg` | 행·열·인물 bbox 및 디버깅 근거 |
| 검수 작업 상태 | OCR 결과 폴더의 `review_state.json` | 수작업 정정, 확인/거절, 수동 관계 등. 백업 후 변경 |
| 검수된 내보내기 | `reviewed_people.json/csv`, `reviewed_relationships.json/csv` | 사람이 확정/검토 중인 상태를 함께 보관 |
| 공용 인물 레지스트리 | `person_registry.json` | 영구 인물 ID/출처. **저장소 루트에도 파일이 추적되고 있으므로 실험·실행만으로 변경된 내용을 무심코 커밋하지 말 것** |

`review_state.json`과 `person_registry.json`을 초기화하면 UUID 연결과 검수 이력이 손상될 수 있습니다. 별도 테스트용 디렉터리를 사용하고, 실제 데이터 변경은 의도·백업·차이를 확인한 후 진행하세요. `.gitignore`가 모든 임시 파일이나 검수 산출물을 자동으로 제외한다고 가정하지 말고, 커밋 전에 `git status`로 검토하세요.

## 19. 안전한 개발 및 검수 절차

1. **문제 확인:** 재현 환경(원본 파일명, 선택 인물, OCR 결과 폴더, 실행 명령/에러)을 적고, `git status`로 이미 있는 사용자 변경을 보존합니다.
2. **범위 선택:** 18절의 책임 파일부터 읽고 변경을 최소화합니다. OCR 후보/검수 상태/영구 ID를 섞는 리팩터링은 별도의 데이터 마이그레이션 없이 하지 않습니다.
3. **구현:** 기존 확정된 검수 정보와 `review_state.json`의 읽기 호환성을 유지합니다. 화면 단축을 위해 원본 OCR 증거를 삭제하지 않습니다.
4. **검증:** `python -m unittest discover -s tests -v`와 수정한 Python 파일의 문법 검사를 실행합니다. 데스크톱 UI를 수정했다면 실제 화면의 클릭/줌/팬도 별도로 검증합니다. UI가 실행되지 않은 경우 **실제 데스크톱 조작 검증 미수행**이라고 명시합니다.
5. **검수:** 1987년 샘플 `scan/001.jpg`의 인명·부모/자녀와 OCR bbox를 비교하되, OCR confidence를 정답으로 간주하지 않습니다. 속도 측정은 최초 모델 초기화 비용과 페이지 추론 시간을 구분합니다.
6. **커밋:** `git diff`와 `git status`로 스캔·레지스트리·검수 결과의 의도치 않은 변경이 없는지 확인합니다. 관련 테스트와 **이 README만** 갱신하고 별도 버전별 README를 만들지 않습니다.
7. **공유:** 적용 결과, 테스트 범위, 한계, 커밋 SHA를 보고합니다. `main` 반영은 사용자의 작업 요청에 따라 수행하고, 다른 작업자의 변경이 생겼다면 덮어쓰기/강제 push를 하지 않습니다.

코딩 에이전트가 작업할 때 추가로 지켜야 할 상세 원칙은 [AGENTS.md](AGENTS.md)를 참고하세요. 중요한 문제 해결·설계 판단·성능 실험의 이유와 결과는 [docs/WORKLOG.md](docs/WORKLOG.md)에 남깁니다. 사소한 변경은 Git 커밋 메시지로 충분하며, 자세한 기록 기준은 AGENTS.md의 **Development history**를 따릅니다.

---

**문서 관리 원칙:** 새 기능이 추가되면 별도의 `README_vX.md`를 만들기보다 이 `README.md`를 갱신합니다. 큰 변경은 [버전별 기능 이력](#15-버전별-기능-이력)에 한 줄을 추가하고, 설치/실행 방법이나 데이터 구조가 바뀌면 해당 본문도 함께 수정합니다.
