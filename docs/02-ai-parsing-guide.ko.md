# AI 세보 파싱 가이드

> 이 문서는 AI Vision 모델에 족보 페이지를 판독시키기 위한 기준 문서다.  
> 실제 호출 시에는 마지막의 **프롬프트 템플릿**을 사용한다.  
> 원칙: **AI는 읽는 보조자다. 최종 판단은 사람이 한다. 불확실하면 비운다.**

---

## 1. 입력과 출력

### 입력

한 번에 **한 페이지**(또는 한 페이지의 한 블록)를 넣는다. 페이지 전체를 여러 번 호출할 경우 블록 좌표를 함께 넘긴다.

```json
{
  "section": "genealogy",
  "printed_page_no": 25,
  "page_type_hint": "genealogy",
  "image_path": "data/pages/genealogy/0025.jpg",
  "width": 705,
  "height": 940
}
```

- `section`: `frontmatter`(전편) 또는 `genealogy`(본편).
- `printed_page_no`: 책에 인쇄된 면번호. 파일명과 다를 수 있다.
- `page_type_hint`: `genealogy`, `generation_table`, `preface`, `photo`, `index`, `generation_name_table`, `property`, `officers`, `subscription`, `colophon`, `cover`, `unknown`.
- 좌표는 이미지 기준 정규화 값(0~1000)으로 통일한다.

### 출력

**JSON만 출력한다.** 마크다운 코드블록, 설명 문장, 인사말을 붙이지 않는다.

```json
{
  "page": {
    "section": "genealogy",
    "printed_page_no": 25,
    "page_type": "genealogy",
    "quality": {
      "rotation_degrees": 0,
      "blur": "low",
      "bleed_through": "medium",
      "needs_human": false
    },
    "subjects": [
      {
        "raw_name": "子仁居",
        "name_hanja": "仁居",
        "name_hangul": null,
        "prefix": "子",
        "bbox": [640, 60, 690, 140],
        "confidence": 0.95
      }
    ]
  },
  "entries": [
    {
      "row": 1,
      "relation_to_subject": "son",
      "person": {
        "raw_name": "子時興",
        "name_hanja": "時興",
        "name_hangul": null,
        "prefix": "子",
        "ja": null,
        "ho": null,
        "generation_no": null,
        "generation_char": null,
        "birth": {
          "raw": null,
          "ganji": null,
          "date_text": null,
          "certainty": "unknown"
        },
        "death": {
          "raw": null,
          "ganji": null,
          "date_text": null,
          "certainty": "unknown"
        },
        "burial": {
          "raw": null,
          "location": null,
          "direction": null,
          "certainty": "unknown"
        },
        "offices": [],
        "spouses": [],
        "children": [
          {
            "raw_name": "子萬元",
            "name_hanja": "萬元",
            "prefix": "子",
            "relation": "son",
            "page_ref": {
              "raw": "上159",
              "target_section": "genealogy",
              "target_page_no": 159
            }
          }
        ],
        "page_ref": null,
        "bbox": [600, 150, 690, 260],
        "confidence": 0.9,
        "needs_human": false
      }
    }
  ],
  "page_refs": [
    {
      "raw": "上159",
      "target_section": "genealogy",
      "target_page_no": 159,
      "source_bbox": [600, 220, 690, 240],
      "confidence": 0.9
    }
  ],
  "unreadable_regions": [],
  "notes": [],
  "validation": {
    "errors": [],
    "warnings": []
  }
}
```

---

## 2. 절대 규칙

1. **원문 보존**: 한자를 번역하거나 간체자로 바꾸지 않는다. 이체자·속자도 원형을 살린다.
2. **읽기 순서**: 오른쪽 위 → 아래 → 왼쪽. 세로쓰기 컬럼을 따른다.
3. **기준 인물**: 페이지 오른쪽 위(또는 첫 열)의 인물이 그 페이지의 기준 인물이다. `子` 접두어는 “이전 페이지 기준 인물의 아들”이라는 뜻이다.
4. **행 = 자녀**: 행을 세대로 오해하지 않는다. 행 아래에 손자가 이어질 수 있다.
5. **`上###`와 `下###`는 페이지 참조**: 
  - `上###`: “본편 ###면에 부모(조상) 기록이 있다”는 뜻.
  - `下###`: “본편 ###면에 자손 기록이 이어진다”는 뜻. 
  - `T`나 `F`로 오독하지 않는다. 이름/숫자/직함으로 해석하지 않는다.
6. **모르면 비운다**: `null`, `unreadable`, `needs_human`을 사용한다. 추측해서 이름을 만들지 않는다.
7. **혼동하기 쉬운 글자**: `子`와 `字`, `女`와 `汝`, `配`와 `妃`, `墓`와 `基`, `上`/`下`와 `T`/`F`, `杜`와 `社`, `慶`과 `廣`, `寧`과 `靈`, `喆`과 `哲`, `鎭`과 `鎮`을 구분한다.
8. **생몰**: `生`/`卒` 뒤의 간지 원문을 유지한다. 명시적 서기 연도가 없으면 임의로 환산하지 않는다.
9. **관계 단정 금지**: `配`, `子`, `女`, `上` 등 명시적 표기가 있을 때만 관계를 단정한다. 없으면 `candidate` 또는 `unknown`.
10. **페이지 유형**: `genealogy`가 아니면 `page_type`만 채우고 `entries`는 비운다. 단, `generation_table`(본편 1면)은 예외다.

---

## 3. 페이지 유형별 처리

| page_type | 처리 |
|---|---|
| `genealogy` | 기준 인물 + 행(자녀) + 손자 + `上###` 파싱 |
| `generation_table` | 본편 1면처럼 1~6세를 한 표로 정리. `blocks[]`에 세대별 인물 |
| `preface` | 서문/추고/번역문. `page_texts`만 추출하고 인물은 만들지 않음 |
| `photo` | 묘소·제각·정려 사진. 캡션만 `captions[]`로 추출 |
| `generation_name_table` | 항렬표(전편 63면). `generation_char` 표로 추출 |
| `index` | 조견색인. 이름 + 참조 페이지를 `index_entries[]`로 추출 |
| `property` | 종중재산목록. 표/텍스트만 추출 |
| `officers` | 임원록(본편 936면). 이름/직책/주소를 표로 추출 |
| `subscription` | 수단(본편 937면). 이름/금액/주소를 표로 추출 |
| `colophon` | 간기(본편 938면). 발행/인쇄 정보만 추출 |
| `cover` | 표지. 텍스트만 추출 |
| `unknown` | `needs_human=true`, `notes`에 이유 |

전편 63면 항렬표는 `scan/frontmatter/063.jpg`다. 세대별로 3개의 항렬자 후보와 이름에서의 위치(앞/가운데/뒤)를 표로 추출한다. 정확한 적용 규칙은 문중 확인이 필요하다.

---

## 4. 필드 정의

### `page.subjects[]`

- `raw_name`: 인쇄된 그대로. 예: `子仁居`.
- `name_hanja`: 접두어를 제거한 이름. 예: `仁居`.
- `name_hangul`: 확실할 때만. 모르면 `null`.
- `prefix`: `子`, `女`, `配`, `婦`, `婿`, `系`, 없음 등.
- `bbox`: 정규화 좌표 `[x1, y1, x2, y2]`.
- `confidence`: 0~1.

### `entries[]`

- `row`: 페이지 안의 행 번호(위에서 아래로 1부터).
- `relation_to_subject`: `son`, `daughter`, `wife`, `husband`, `grandson`, `granddaughter`, `son_in_law`, `daughter_in_law`, `unknown`.
- `person`: 아래 필드.
- `bbox`: 행 전체 또는 인물 영역.
- `confidence`: 0~1.
- `needs_human`: 불확실하면 `true`.

### `person`

- `raw_name`: 인쇄된 그대로.
- `name_hanja`: 접두어 제거.
- `name_hangul`: 확실할 때만.
- `prefix`: `子`, `女`, `配` 등.
- `ja`: `字` 뒤의 값.
- `ho`: `號` 뒤의 값.
- `generation_no`: **명시적 `世` 표기가 있을 때만** 채운다. 행 번호로 추정하지 않는다. 추정이 필요하면 `generation_hint`에 근거와 함께 넣고 `needs_human=true`.
- `generation_char`: 이름에서 확인되는 항렬자. 확실할 때만.
- `birth` / `death`: `raw`, `ganji`, `date_text`, `certainty`.
  - `raw`: 원문 전체.
  - `ganji`: `壬子`, `丁卯` 같은 간지.
  - `date_text`: `1929년 11월 17일`처럼 원문에 있는 서기/음력 표기.
  - `certainty`: `exact`, `probable`, `uncertain`, `unknown`.
- `burial`: `raw`, `location`, `direction`, `certainty`.
  - `location`: 묘소 지명.
  - `direction`: `艮坐坤向` 같은 좌향.
- `offices`: 관직/칭호 배열. 원문 유지.
- `spouses[]`: 배우자. `raw_name`, `name_hanja`, `bonkwan`, `father`, `certainty`.
- `children[]`: 자녀. `raw_name`, `name_hanja`, `prefix`, `relation`, `page_ref`.
- `page_ref`: 그 인물의 상세 기록 페이지. `raw`, `target_section`, `target_page_no`.
- `bbox`: 인물 영역.
- `confidence`: 0~1.
- `needs_human`: 불확실하면 `true`.

### `page_refs[]`

- `raw`: `上159` 원문.
- `target_section`: 기본 `genealogy`. 전편을 가리키면 `frontmatter`.
- `target_page_no`: 정수.
- `source_bbox`: 참조가 인쇄된 위치.
- `confidence`: 0~1.

### `unreadable_regions[]`

- `bbox`, `reason`: `blur`, `bleed_through`, `cut_off`, `unknown_char` 등.

---

## 5. `女` 행의 특별 규칙

전통 세보에서 `女` 뒤에 나오는 이름은 **딸의 이름이 아니라 사위의 이름**인 경우가 많다. 예: `女崔欽祖` = “딸이 崔欽祖에게 출가”.

따라서 다음 원칙을 적용한다.

1. `女` 행의 `relation_to_subject`는 `daughter`.
2. `person.name_hanja`는 **딸의 이름이 인쇄되어 있으면** 그 값을 넣고, 아니면 `null`.
3. 뒤에 나오는 남성 이름은 `person.spouses[]`에 `son_in_law`로 넣는다. 예: `spouse.raw_name = "崔欽祖"`, `spouse.relation = "son_in_law"`, `spouse.bonkwan = "晋州"`.
4. 딸의 이름과 사위의 이름이 모두 있는지, 사위만 있는지 확실하지 않으면 `needs_human=true`.
5. `女` 행을 아들의 배우자로 해석하지 않는다.

`配`는 남성 기준 배우자(주로 아내)다. `配` 뒤에는 처가의 본관/성씨/아버지 이름이 올 수 있다.

---

## 6. 레이아웃 규칙

1. 페이지 프레임 안쪽만 읽는다. 스캔 여백/손가락/그림자는 무시한다.
2. 세로 컬럼은 오른쪽에서 왼쪽으로 읽는다.
3. 페이지 오른쪽 위의 큰 글씨가 기준 인물이다. 페이지 제목·`派`·`世` 표기는 `page.header`로 분리한다.
4. 한 행에 여러 사람이 있을 수 있다. `row`와 `column`을 함께 기록한다.
5. 행의 오른쪽 = 자녀 이름, 왼쪽 = 배우자/자녀/묘소/생몰. 같은 행의 텍스트를 한 사람으로 합치지 않는다.
6. 행 아래의 손자 목록은 `person.children[]`에 넣는다. 다음 행의 자녀로 오해하지 않는다.
7. 한글 측주/메모는 `annotations[]`에 넣고, 한자 이름과 합치지 않는다.
8. 사진/캡션은 `captions[]`에 넣고 인물로 만들지 않는다.
9. 페이지가 90도/180도 회전되어 있으면 `quality.rotation_degrees`에 기록하고 `needs_human=true`.
10. 뒷면 비침이 심하면 `quality.bleed_through="high"`로 기록한다. 글자가 겹쳐 보여도 추측하지 않는다.

---

## 7. Few-shot 예시

### 본편 25면

- 기준 인물: `子仁居`.
- 행: `子時興`, `女崔欽祖`, `女美海擎`, `子榮茂`, `子連泰`.
- 손자: `子萬元 上159`, `子萬迪 上168`, `子萬純 上170`.
- `女崔欽祖`는 “딸이 崔欽祖에게 출가”로 읽고, 딸 이름은 `null`, 사위 이름은 `崔欽祖`로 분리한다.

### 본편 217면

- 기준 인물: `子洪東` (字 龍山, 1929년생).
- 행: `女美諧順`, `子洪覺`, `子澈秀 上738`.
- 洪東의 딸 美諧順, 아들 洪覺, 아들 澈秀. 澈秀의 상세 기록은 본편 738면.

### 본편 1면

- `page_type = generation_table`.
- `一世 杜慶寧`, `二世 杜子建`, `三世 杜宣龍` ... `六世`까지.
- 여기서는 행이 세대다. 일반 세보 페이지와 혼동하지 않는다.

### 본편 63면

- `萬元 上15`가 먼저 나오고, 아래에 `子碩喆`, `子光林`, `子德巖`, `子永眞`, `子洪良`이 이어진다.
- `萬元`의 상세 기록은 본편 15면.
- 기준 인물과 아래 `子`들의 정확한 관계는 `needs_human=true`로 표시한다.

---

## 8. 자기 검증

출력 전에 다음을 확인하고 `validation`에 기록한다.

- [ ] 모든 `page_refs[].target_page_no`가 해당 섹션 범위 안에 있는가? (본편 1~938, 전편 1~93)
- [ ] `name_hanja`가 비어 있는데 `raw_name`도 비어 있지 않은가?
- [ ] `子`/`女`/`配` 접두어를 `name_hanja`에 포함하지 않았는가?
- [ ] `女` 행의 이름을 딸 이름으로 잘못 넣지 않았는가?
- [ ] `上###`를 `T###`로 읽지 않았는가?
- [ ] 행 번호로 세대를 추정하지 않았는가?
- [ ] `page_type`이 `genealogy`/`generation_table`이 아닌데 `entries`가 비어 있는가?
- [ ] `confidence < 0.8`인 항목에 `needs_human=true`가 붙었는가?
- [ ] 회전/블러/비침이 심한 페이지에 `quality.needs_human=true`가 붙었는가?

---

## 9. 프롬프트 템플릿

### System

```text
너는 1986년 간행 한국 전통 족보 『杜陵杜氏世譜』(金浦派)를 판독하는 전문가다.
너의 임무는 페이지 이미지를 읽어 구조화된 JSON으로 출력하는 것이다.

규칙:
1. 세보는 오른쪽에서 왼쪽으로, 위에서 아래로 읽는다.
2. 페이지 오른쪽 위(또는 첫 열)의 인물이 기준 인물이다. `子`는 이전 페이지 기준 인물의 아들이다.
3. 행은 자녀다. 행 아래는 손자다. 행을 세대로 오해하지 않는다.
4. `上159`는 본편 159면 참조다. `T159`가 아니다. 이름이나 숫자로 해석하지 않는다.
5. `子`는 아들, `女`는 딸(뒤에 사위 이름이 올 수 있음), `配`는 배우자다.
6. `女` 뒤의 남성 이름은 사위다. 딸 이름으로 넣지 않는다.
7. `子`와 `字`, `女`와 `汝`, `配`와 `妃`, `墓`와 `基`, `上`와 `T`, `杜`와 `社`를 구분한다.
8. 한자를 번역하거나 간체자로 바꾸지 않는다.
9. 생몰의 간지를 임의로 서기로 환산하지 않는다.
10. 불확실하면 null, unreadable, needs_human을 사용한다. 추측하지 않는다.
11. JSON만 출력한다. 설명 문장, 마크다운, 인사말을 붙이지 않는다.
```

### User

```text
다음 페이지를 판독해 output.schema.json에 맞는 JSON으로 출력하라.

section: {section}
printed_page_no: {printed_page_no}
page_type_hint: {page_type_hint}
image_width: {width}
image_height: {height}

이미지: {image}
```

---

## 10. 평가와 파일럿

- **골든셋**: 실제 페이지 20~30장을 사람이 정답 전사한다. 최소한 본편 1, 25, 63, 217, 936, 938면과 전편 1, 47, 63면을 포함한다.
- **지표**:
  - 문자 오류율(CER): 한자 이름/지명/관직.
  - 필드 F1: 이름, 字/號, 생몰 간지, 배우자, 자녀, `上###`.
  - 관계 precision/recall: 부모-자녀, 배우자.
  - 페이지 유형 분류 정확도.
- **모델 비교**: 같은 20장에 여러 무료/로컬 모델을 돌려 비교한다. 모델별로 잘 읽는 페이지가 다를 수 있으므로 앙상블을 고려한다.
- **게이트**: 골든셋에서 이름/관계 F1이 목표(예: 0.95)에 못 미치면 전체 935면을 돌리지 않는다. 프롬프트/전처리/모델을 먼저 개선한다.

---

## 11. 무료 API 사용 시 제약

- **Rate limit**: 무료 티어는 분당/일일 요청 수가 작다. 935면 × 블록 크롭을 한 번에 보내지 말고, 제공자별 quota를 DB에 기록하며 큐로 처리한다.
- **체크포인트**: `(image_sha256, prompt_version, page_id, block_id)` 단위로 결과를 저장해 중단점부터 이어간다.
- **캐시**: 같은 이미지/프롬프트는 재호출하지 않는다.
- **Fallback**: 한 제공자가 실패하면 다른 무료 제공자/로컬 PaddleOCR로 넘긴다.
- **데이터 정책**: 무료 API는 입력 데이터를 로그/학습에 사용할 수 있다. 문중 기록을 외부로 보내도 되는지 확인한다. 불가하면 로컬 OCR/로컬 VLM으로 전환한다.
- **비용 기록**: 무료라도 토큰/호출 수를 기록해 병목을 파악한다.

---

## 12. 사람 검수와의 연결

AI 출력은 바로 공개하지 않는다.

1. AI가 `draft`를 만든다.
2. 규칙 검증기가 오류/경고를 표시한다.
3. 검수자는 `confidence`가 낮은 항목, 관계 이상, `上###` 불일치부터 확인한다.
4. 검수자가 승인한 항목만 `published`로 이동한다.
5. 모든 수정은 `review_actions`에 기록한다.

AI의 목표는 “완벽한 자동 추출”이 아니라 **사람이 검수할 수 있는 초안을 최소한의 비용으로 만드는 것**이다.
