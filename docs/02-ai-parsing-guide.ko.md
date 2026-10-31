# AI 세보 파싱 가이드

> 이 문서는 AI Vision 모델에 족보 페이지를 판독시키기 위한 기준 문서다.  
> 실제 호출 시에는 **§2 판독 규칙**을 그대로 프롬프트로 보낸다.  
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
- `page_type_hint`: `genealogy`, `preface`, `photo`, `index`, `generation_name_table`, `property`, `officers`, `subscription`, `colophon`, `cover`, `unknown`.
- 좌표는 이미지 기준 정규화 값(0~1000)으로 통일한다.

### 출력

**JSON만 출력한다.** 마크다운 코드블록, 설명 문장, 인사말을 붙이지 않는다.

아래는 본편 25면을 축약한 예시다. 전체 필드 정의는 §4를 따른다. `subjects[]`도 `entries[].person`과 같은 필드를 가질 수 있지만, 예시에서는 이름만 남겼다.

```json
{
  "page": {
    "section": "genealogy",
    "printed_page_no": 25,
    "page_type": "genealogy"
  },
  "entries": [
    {
      "row": 1,
      "column": 1,
      "generation_offset": 1,
      "relation_to_subject": "son",
      "person": {
        "raw_name": "子時興",
        "name_hanja": "時興",
        "prefix": "子",
        "page_ref": null,
        "birth": {
          "raw": "孝宗辛卯九月二十六日生",
          "king_era": "孝宗",
          "ganji": "辛卯",
          "date_text": "九月二十六日"
        },
        "death": {
          "raw": "肅宗戊戌十二月九日卒",
          "king_era": "肅宗",
          "ganji": "戊戌",
          "date_text": "十二月九日"
        },
        "burial": {
          "raw": "墓沃溝郡沃溝面屯山里先堂東麓甲坐有碣",
          "location": "전라북도 沃溝郡 沃溝面 屯山里 先堂 東麓",
          "orientation": "甲坐",
          "note": "有碣"
        },
        "aliases": [
          { "type": "字", "value": "成五" },
          { "type": "號", "value": "𡸡彛" }
        ],
        "offices": [],
        "spouses": [
          {
            "raw_name": "配全州柳氏",
            "name_hanja": "柳氏",
            "bonkwan": "全州",
            "father": null,
            "burial": {
              "raw": "墓沃溝郡澶縣面舊尺洞西麓先堂砌下壬坐有表碣",
              "location": "沃溝郡 澶縣面 舊尺洞 西麓 先堂 砌下",
              "orientation": "壬坐",
              "note": "有表碣"
            },
            "relation": "wife"
          },
          {
            "raw_name": "配晉州姜氏",
            "name_hanja": "姜氏",
            "bonkwan": "晉州",
            "father": "錫琪",
            "burial": {
              "raw": "墓沃溝郡沃溝面屯山里先堂東麓甲坐公墓上下封有碣",
              "location": "沃溝郡 沃溝面 屯山里 先堂 東麓 公墓 上下",
              "orientation": "甲坐",
              "note": "上下封 有碣"
            },
            "relation": "wife"
          }
        ],
        "notes": []
      }
    }
  ]
}
```

---

## 2. 판독 규칙 — 프롬프트 정본

> 이 절이 **유일한 정본**이다. 호출 시 `2.1`~`2.2`를 그대로 System 메시지로, `2.4`를 User 메시지로 보낸다.  
> 다른 절에서 같은 규칙을 다시 쓰지 않는다. 규칙을 고칠 때는 여기만 고친다.  
> §5·§6·§8은 이 절을 특정 상황에 적용한 것이므로, §2와 어긋나면 §2를 따른다.

### 2.1 역할

너는 1986년 간행 한국 전통 족보 『杜陵杜氏世譜』(金浦派)를 판독하는 전문가다.  
너의 임무는 페이지 이미지를 읽어 구조화된 JSON으로 출력하는 것이다.

### 2.2 규칙

1. **원문 보존**: 한자를 번역하거나 간체자로 바꾸지 않는다. 이체자·속자도 원형을 살린다.
2. **읽기 순서**: 위에서 아래로(단 순서), 각 단 안에서는 오른쪽에서 왼쪽으로 읽는다. 세로쓰기 컬럼은 이름·배우자·생몰 등이 왼쪽으로 이어지는 순서다.
3. **기준 인물(subject)**: 기준 인물은 **첫 단에서 페이지를 시작하는 인물**이다. 보통 `子`가 붙은 사람이고, 페이지가 새로 시작하면 `子` 없이 이름만 적고 `上###`로 아버지를 가리키기도 한다. 같은 단 오른쪽에 `女` 항목이 올 수 있으며, 이때 `女`는 `entries[]`에 같은 단으로 넣는다. `子`는 “위 단(또는 앞 페이지)의 직계 인물의 아들”이라는 표시다.
4. **단(段) = 세대**: 페이지를 가로로 나눈 줄이 단이다. **원칙적으로 같은 단 = 같은 세대**이고, 한 단 안에서는 **오른쪽→왼쪽**(아들 형제는 장남→차남)으로 읽는다. 딸(`女`) 항목의 위치는 페이지마다 다를 수 있으므로 `女` 표시로 구분한다. **원칙적으로 바로 아래 단은 다음 세대**다. 한 줄을 “한 사람의 자녀 목록”으로 읽지 않는다. 아래 단을 손자로 건너뛰지도 않는다. 다만 딸의 자손(외손)이 작은 글씨로 딸 항목 아래에 붙는 경우, **인쇄된 단과 실제 세대가 다를 수 있으므로** 단 경계만으로 세대를 단정하지 않는다.
5. **`上###`·`下###`는 페이지 참조**: `上###`은 “본편 ###면에 부모(조상)의 기록이 있다”, `下###`은 “본편 ###면에 자손의 기록이 이어진다”는 뜻이다. `見上十三`처럼 `見上`이 붙거나 숫자가 한자일 수 있다. 스캔에서 `T###`·`F###`로 보이는 것은 `下###`의 오독이다. 이름·숫자·직함으로 해석하지 않는다.
6. **`子`·`女`·`配`·`系`**: `子`는 아들, `女`는 딸(뒤에 사위 이름이 올 수 있음), `配`는 배우자, `系`는 양자다.
7. **`女` 뒤의 남성 이름은 대개 사위다**: 성씨가 붙은 남성 이름이 오면 사위로 읽는 것이 기본이고, 딸 이름으로 단정하지 않는다. 딸 이름이 따로 인쇄된 경우와 구분한다.
8. **혼동하기 쉬운 글자**: `子`와 `字`, `女`와 `汝`, `配`와 `妃`, `墓`와 `基`, `上`/`下`와 `T`/`F`, `杜`와 `社`, `慶`과 `廣`, `寧`과 `靈`, `喆`과 `哲`, `鎭`과 `鎮`을 구분한다.
9. **생몰**: `生`/`卒` 뒤의 간지 원문을 유지한다. 명시적 서기 연도가 없으면 임의로 환산하지 않는다.
10. **관계 단정 금지**: `配`, `子`, `女`, `上`, `下` 등 명시적 표기가 있을 때만 관계를 단정한다. 단 위치만으로 부모를 특정하지 않는다. 위 단에 한 명뿐이면 그 사람의 자녀로 볼 수 있지만, 여러 명이면 `descendant`로 두고 `needs_human=true`. 표기가 없으면 `unknown`.
11. **페이지 유형**: `genealogy`가 아니면 `page_type`만 채우고 `entries`는 비운다. 인물이 아닌 내용은 `captions[]`·`index_entries[]` 등 해당 보조 필드에 넣는다.
12. **모르면 비운다**: `null`, `unreadable`, `needs_human`을 사용한다. 추측해서 이름을 만들지 않는다.
13. **JSON만 출력한다**: 설명 문장, 마크다운 코드블록, 인사말을 붙이지 않는다.

### 2.3 출력 형식

- `page_type`이 `genealogy`이면 §1 예시와 §4 필드 정의에 맞춰 `entries`를 채우고, 그 외 유형은 `entries`를 빈 배열로 둔다.
- 이것은 구현자용 메모다. 프롬프트 본문에는 2.2의 13번과 아래 `{schema}`만 있으면 된다.

### 2.4 User 템플릿

```text
다음 페이지를 판독해 {schema}에 맞는 JSON으로 출력하라.

section: {section}
printed_page_no: {printed_page_no}
page_type_hint: {page_type_hint}
image_width: {width}
image_height: {height}

이미지: {image}
```

- `{schema}`에는 `schema/page.schema.json`을 그대로 넣는다. `scripts/prompt.py`가 이 문서 §2.1·§2.2와 스키마를 합쳐 프롬프트를 만든다.

---

## 3. 페이지 유형별 처리

| page_type | 처리 |
|---|---|
| `genealogy` | 단(세대)별 인물 + `上`/`下` 참조 파싱. 같은 단은 원칙적으로 같은 세대, 아래 단은 다음 세대. 본편 1면도 이 유형이다 |
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

전편 63면 항렬표는 `scan/frontmatter/063.jpg`다. 세대별로 3개의 항렬자 후보와 이름에서의 위치(앞/가운데/뒤)를 표로 추출한다. 본편 63면(`scan/genealogy/063.jpg`) 세보와 혼동하지 않는다.

---

## 4. 필드 정의

좌표는 모두 이미지 기준 정규화 값 `[x1, y1, x2, y2]`(0~1000)이다.

### `page`

- `section`: `frontmatter` | `genealogy`.
- `printed_page_no`: 인쇄된 면번호(정수).
- `page_type`: §3의 값.
- `quality`: `rotation_degrees`, `blur`(`low`|`medium`|`high`), `bleed_through`(`low`|`medium`|`high`), `needs_human`.
- `header`: 페이지 상단/여백의 제목·`派`·`世` 표기, 기준 인물 위의 아버지 이름.
  - `running_head`: 페이지 가장자리에 인쇄된 큰 이름표(없으면 `null`). 인물 항목과 혼동하지 않는다.
  - `father_name`: 기준 인물 위에 작은 글씨로 붙은 아버지 이름(없으면 `null`).
  - `notes`: 그 밖의 머리말.
- `subjects[]`: 그 페이지의 **기준 인물**. 첫 단에서 페이지를 시작하는 인물(보통 `子`가 붙은 사람)이다. 보통 1명. 여기 넣은 인물은 `entries[]`에 다시 넣지 않는다.
  - `row`, `column`, `page_ref`, `bbox`, `confidence`, `needs_human`.
  - 이름·자·호·생몰·묘소·배우자·자녀 등은 `entries[].person`과 같은 필드로 기록한다(`raw_name`, `name_hanja`, `name_hangul`, `prefix`, `aliases[]`, `generation_no`, `generation_hint`, `generation_char`, `birth`, `death`, `burial`, `offices`, `spouses[]`, `children[]`).
  - `children[]`은 그 인물 항목 안에 자녀 이름이 함께 인쇄된 경우에만 쓰고, 페이지의 단으로 표현된 자녀는 `entries[]`에 둔다.

### `entries[]`

페이지에 인쇄된 인물 항목. **단(段)별로** 기록한다.

- `row`: **단 번호**. 맨 위 단이 1. 같은 단의 인물은 같은 `row` 값을 쓴다.
- `column`: 단 안에서 **오른쪽부터** 1, 2, 3… (오른쪽이 1).
- `generation_offset`: **기준 인물 기준** 실제 상대 세대. 0=기준 인물과 같은 세대, 1=한 세대 아래, 2=두 세대 아래… **절대 세대수가 아니다.** 보통은 단 차이와 같지만, 외손이 작은 글씨로 붙은 경우 `row`(인쇄된 단)와 다를 수 있다. `row` 번호로 세대수를 추정하지 않는다.
- `relation_to_subject`: 기준 인물과의 관계. `self`, `son`, `daughter`, `brother`, `sister`, `sibling`, `grandson`, `granddaughter`, `descendant`, `spouse`, `son_in_law`, `daughter_in_law`, `unknown`. 기준 인물과 같은 세대면 `self`/`brother`/`sister`/`sibling`/`spouse`, 한 세대 아래이고 부모가 특정되면 `son`/`daughter`, 두 세대 아래이고 관계가 분명하면 `grandson`/`granddaughter`, 그 외에는 `descendant`로 둔다. **같은 단의 형제·자매 관계는 `row`가 같다는 사실로도 표현된다.**
- `person`: 아래 필드.
- `bbox`: 그 인물 항목 전체.
- `confidence`: 0~1.
- `needs_human`: 불확실하면 `true`.

### `person`

- `raw_name`: 인쇄된 그대로.
- `name_hanja`: 접두어 제거.
- `name_hangul`: 확실할 때만.
- `prefix`: `子`, `女`, `配`, `系`, 없음 등.
- `aliases[]`: `字`·`號`·이칭. `{ "type": "字"|"號"|"其他", "value": "<한자>" }`. `type`이 불확실하면 `其他`로 두고 `needs_human=true`.
- `generation_no`: **페이지에 명시적으로 인쇄된 `世` 표기가 있을 때만** 채운다. 여백의 `世` 표기가 뒷면 비침이면 세지 않는다. `row`나 `generation_offset`으로 절대 세대수를 추정하지 않는다.
- `generation_hint`: `世` 표기가 없을 때의 추정. `{ "value": <추정 세대>, "basis": "항렬자·1면 세대표·부모-자녀 연결", "certainty": "probable" }`처럼 근거를 함께 적고 `needs_human=true`.
- `generation_char`: 이름에서 확인되는 항렬자. 확실할 때만.
- `birth` / `death`: `raw`, `king_era`, `ganji`, `date_text`, `certainty`(`exact`|`probable`|`uncertain`|`unknown`).
  - `king_era`: `生`/`卒` 앞에 인쇄된 연호(예: `孝宗`, `肅宗`). 없으면 `null`.
  - `ganji`: 간지 두 글자(예: `辛卯`). 없으면 `null`.
  - `date_text`: 간지 뒤의 월·일 원문(예: `九月二十六日`).
- `burial`: `raw`, `location`, `orientation`, `note`, `certainty`.
  - `location`: 묘소 소재지. 원문을 존중하되 행정구역 단위로 띄어 쓴다.
  - `orientation`: 좌향(예: `甲坐`, `壬坐`). 없으면 `null`.
  - `note`: `有碣`, `有表碣`, `上下封`처럼 묘비·봉분에 대한 부기.
- `offices`: 관직/칭호 배열. 원문 유지.
- `spouses[]`: 배우자.
  - `raw_name`, `name_hanja`, `bonkwan`, `father`, `relation`, `burial`, `certainty`.
  - `relation`: `wife`, `husband`, `son_in_law`, `daughter_in_law`, `unknown`.
  - `burial`: `person.burial`과 같은 구조.
- `children[]`: 그 인물 항목 안에 자녀 이름이 함께 인쇄된 경우에만 채운다. 페이지의 단으로 표현된 자녀는 `entries[]`에 두고 여기에 중복해서 넣지 않는다. `raw_name`, `name_hanja`, `prefix`, `relation`, `page_ref`.
- `page_ref`: 그 인물의 **조상(上) 또는 자손(下)** 기록 페이지. 아래 `page_ref` 정의를 따른다. 참조가 없으면 `null`.
- `bbox`, `confidence`, `needs_human`.

### `page_ref`

`上###`·`下###` 참조 하나를 그 자리에서 표현한다. DB 적재 시 `page_refs` 테이블로 분리한다.

- `raw`: 인쇄된 그대로. 예: `上159`, `見上十三`, `下4`.
- `direction`: `up`(조상/부모) | `down`(자손).
- `target_section`: 기본 `genealogy`. 전편을 가리키면 `frontmatter`.
- `target_page_no`: 정수. 한자 숫자는 변환한다(十三 → 13).
- `bbox`: 참조가 인쇄된 위치.
- `confidence`: 0~1.

`subjects[].page_ref`, `person.page_ref`, `children[].page_ref`는 모두 이 구조를 쓴다. 같은 참조를 배열과 인물 양쪽에 중복 저장하지 않는다.

### 페이지 유형별 보조 필드

- `captions[]`: `photo`의 캡션. `{ "raw": "...", "bbox": [...] }`.
- `index_entries[]`: `index`의 색인 항목. `{ "name_hanja": "...", "name_hangul": null, "page_ref": {...} }`.
- `annotations[]`: 한글 측주·메모. `{ "raw": "...", "bbox": [...], "kind": "note"|"address"|"burial"|"other" }`.
- `page_texts[]`: `preface`·`colophon` 등 인물 항목이 아닌 본문. `{ "raw": "...", "bbox": [...], "kind": "body"|"heading"|"colophon"|"other" }`.
- `generation_chars[]`: `generation_name_table`(전편 63면)의 항렬자. `{ "generation_no": 21, "position": "앞"|"가운데"|"뒤", "chars": ["基", "鍾", "洪"], "bbox": [...] }`.
- `tables[]`: `property`·`officers`·`subscription` 등 표. `{ "title": "...", "headers": [...], "rows": [[...]], "bbox": [...] }`.

### `unreadable_regions[]`

- `bbox`, `reason`: `blur`, `bleed_through`, `cut_off`, `unknown_char` 등.

---

## 5. `女` 항목의 특별 규칙

전통 세보에서 `女` 뒤에 오는 이름은 **딸의 이름이 아니라 사위의 이름**인 경우가 많다. 예: `女崔欽祖` = “딸이 崔欽祖에게 출가”.

따라서 다음 원칙을 적용한다.

1. `女` 항목의 `relation_to_subject`는 기준 인물과의 관계로 정한다. 기준 인물과 같은 세대면 `sister`/`sibling`, 한 세대 아래면 `daughter`, 그 아래면 `descendant`다.
2. `person.name_hanja`는 **딸의 이름이 인쇄되어 있으면** 그 값을 넣고, 아니면 `null`.
3. 뒤에 나오는 남성 이름은 `person.spouses[]`에 `son_in_law`로 넣는다. 예: `spouse.raw_name = "崔欽祖"`, `spouse.relation = "son_in_law"`, `spouse.bonkwan = "晋州"`.
4. 딸의 이름과 사위의 이름이 모두 있는지, 사위만 있는지 확실하지 않으면 `needs_human=true`.
5. `女` 항목을 아들의 배우자로 해석하지 않는다.
6. `女` 뒤 이름이 여성 이름으로 보이면 딸의 이름일 수 있다. 이때도 사위 이름과 분리하고 `needs_human=true`로 둔다.

`配`는 남성 기준 배우자(주로 아내)다. `配` 뒤에는 처가의 본관/성씨/아버지 이름이 올 수 있다.

---

## 6. 레이아웃 규칙

1. 페이지 프레임 안쪽만 읽는다. 스캔 여백/손가락/그림자는 무시한다.
2. 세로 컬럼은 오른쪽에서 왼쪽으로 읽는다.
3. 첫 단에서 페이지를 시작하는 인물(보통 `子`가 붙은 사람)이 기준 인물이다. 오른쪽에 `女` 항목이 올 수 있으며, 이는 같은 단의 `entries[]`로 넣는다. 페이지 제목·`派`·`世` 표기와 기준 인물 위의 아버지 이름은 `page.header`로 분리한다.
4. 한 단에 여러 사람이 있을 수 있다. `row`(단 번호)와 `column`(단 안 오른쪽부터 1)을 함께 기록한다.
5. 단의 오른쪽 = 그 세대의 이름, 왼쪽 = 배우자·생몰·묘소·관직 등. 같은 단의 텍스트를 한 사람으로 합치지 않는다.
6. **아래 단은 다음 세대**다. 원칙적으로 위 단 인물의 자녀는 아래 단에 있다. 다만 작은 글씨로 붙은 외손은 인쇄된 단과 실제 세대가 다를 수 있다.
7. 딸의 자손(외손)은 딸 항목 아래에 세로로 이어질 수 있다. 단 경계와 무관하게 붙고, **앞 페이지의 딸 항목**에 붙는 경우도 있으므로 앞 페이지까지 확인한다.
8. `上###`·`下###`·`見上###`는 해당 인물의 `page_ref`에 넣는다. `T###`·`F###`는 `下###`다.
9. 한글 측주/메모는 `annotations[]`에 넣고, 한자 이름과 합치지 않는다.
10. 사진/캡션은 `captions[]`에 넣고 인물로 만들지 않는다.
11. 페이지가 90도/180도 회전되어 있으면 `quality.rotation_degrees`에 기록하고 `needs_human=true`.
12. 뒷면 비침이 심하면 `quality.bleed_through="high"`로 기록한다. 글자가 겹쳐 보여도 추측하지 않는다.

---

## 7. Few-shot 예시

### 본편 25면

- 페이지는 **5개의 단**으로 되어 있다.
- 1단: `子仁居`(맨 오른쪽).
- 2단: `女美海擎`, `女崔欽祖`, `子時興` → 仁居의 자녀 세대. `女` 항목은 딸이고, `崔欽祖`처럼 성씨가 붙은 남성 이름은 사위다. `美海擎`은 딸 이름인지 사위 이름인지 확실하지 않으므로 `needs_human=true`.
- 3단: `子榮茂` → 다음 세대.
- 4단: `子連泰` → 다음 세대.
- 5단: `子萬元`, `子萬迪`, `子萬純`, `子萬成`, `子萬益`, `子萬大`, `子萬赫` → 다시 다음 세대.
- 萬元의 `下159`(스캔에는 `F159`)는 “159면에 자손 기록이 이어진다”는 뜻이다. `上159`가 아니다.
- 5단의 다른 형제들에게도 `下168`·`下170`·`下183`·`下187`·`下188`(스캔에는 `T`/`F`) 같은 참조가 붙는다.
- 萬元을 仁居의 손자로 읽지 않는다. 仁居 기준 `generation_offset=4`다.

### 본편 217면

- 기준 인물: `萬宜`. 
- `萬宜` 위의 작은 글씨 `連泰`는 아버지 이름으로 보이며, `上29`는 그 조상의 기록이 있는 면을 가리킴.
- `萬宜`의 `上29`는 `subjects[0].page_ref`에 `direction=up`, `target_page_no=29`로 둔다.
- 마지막 단의 `澈秀` 아래에는 `下738`(스캔에는 `F738`)이 있어, 738면에 자손 기록이 이어짐을 나타냄.

### 본편 1면

- `page_type = genealogy`. (1세부터 6세까지 계보가 이어진 세보의 시작 페이지)
- `一世 杜慶寧` ... `六世`까지 6개의 단.
- 각 단이 곧 세대. 일반 세보 페이지와 같은 `row`/`column` 규칙 적용.

### 본편 63면

- 기준 인물: `萬元` (1단, `上15`로 조상 확인).
- 6개의 단으로 구성.
- 2단: `女金日長`, `女田權五`, `女姜仁豐`, `子碩喆` → `萬元`의 자녀 세대.
- 3단: `女金東赫`, `子光林` → `碩喆`의 자녀 세대.
- 4단: `子金容琯`(오른쪽 작은 글씨), `女高錫萬`(가운데), `子德巖`(왼쪽) → `德巖`과 `女高錫萬` 항목(딸)은 `光林`의 자녀 세대다. 다만 오른쪽 작은 글씨 `子金容琯`은 앞 페이지 `062.jpg` 4단 가장 왼쪽의 딸(`女金仁斗`)의 아들, 즉 `光林`의 **손자(외손)**다. 인쇄된 단은 4단이지만 4단의 명목 세대(光林의 자녀)보다 한 세대 아래이므로 `needs_human=true`.
- 5단: `子永眞` → `德巖`의 자녀 세대.
- 6단: `子洪良` → `永眞`의 자녀 세대.
- `碩喆`부터 `洪良`까지 `萬元` 기준 `generation_offset=1~5`이고, `金容琯`은 4단에 인쇄되었지만 `generation_offset=4`다.

---

## 8. 자기 검증

출력 전에 다음을 확인한다.

- [ ] 모든 `page_ref.target_page_no`가 해당 섹션 범위 안에 있는가? (본편 1~938, 전편 1~93, 미수록 면 포함)
- [ ] 모든 `page_ref.direction`이 `up`/`down`으로 맞는가? (`上`=up, `下`·`T`·`F`=down)
- [ ] `見上十三` 같은 한자 숫자를 정수로 변환했는가?
- [ ] `name_hanja`가 비어 있어도 `raw_name`은 보존했는가?
- [ ] `子`/`女`/`配`/`系` 접두어를 `name_hanja`에 포함하지 않았는가?
- [ ] `女` 항목의 이름을 사위 이름으로 잘못 넣지 않았는가? (또는 그 반대)
- [ ] **같은 단의 인물을 같은 `row`로 묶었는가?**
- [ ] **원칙적으로 바로 아래 단을 다음 세대로 처리했는가?** (손자로 건너뛰지 않았는가)
- [ ] `generation_offset`이 **기준 인물** 기준인가? (기준 인물은 첫 단에서 페이지를 시작하는 인물이므로 0이다)
- [ ] `row` 번호로 **절대 세대수**를 추정하지 않았는가?
- [ ] 작은 글씨로 붙은 외손은 `row`와 `generation_offset`이 다를 수 있음을 반영했는가?
- [ ] `page_type`이 `genealogy`이면 `entries`가 비어 있지 않은가?
- [ ] 그 외 유형이면 `entries`가 비어 있는가?
- [ ] `subjects[].page_ref`/`person.page_ref`/`children[].page_ref`에 `raw`·`direction`·`target_page_no`가 채워졌는가?
- [ ] 기준 인물 위의 아버지 이름을 `page.header.father_name`에 넣었는가?
- [ ] 여백의 `世` 표기가 뒷면 비침이 아닌지 확인했는가?
- [ ] `confidence < 0.8`인 항목에 `needs_human=true`가 붙었는가?
- [ ] 회전/블러/비침이 심한 페이지에 `quality.needs_human=true`가 붙었는가?

---

## 9. 평가와 파일럿

- **골든셋**: 실제 페이지 20~30장을 사람이 정답 전사한다. 최소한 본편 1, 25, 63, 217, 936, 937, 938면과 전편 1, 47, 63면을 포함한다.
- **지표**:
  - 문자 오류율(CER): 한자 이름/지명/관직.
  - 필드 F1: 이름, 字/號, 생몰 간지, 배우자, 자녀, `上###`/`下###`.
  - 관계 precision/recall: 부모-자녀, 배우자, 같은 단의 형제·자매.
  - 페이지 유형 분류 정확도.
- **모델 비교**: 같은 20장에 여러 무료/로컬 모델을 돌려 비교한다. 모델별로 잘 읽는 페이지가 다를 수 있으므로 앙상블을 고려한다.
- **게이트**: 골든셋에서 이름/관계 F1이 목표(예: 0.95)에 못 미치면 전체 본편 938면(현재 스캔 935장)을 돌리지 않는다. 프롬프트/전처리/모델을 먼저 개선한다.

---

## 10. 무료 API 사용 시 제약

- **Rate limit**: 무료 티어는 분당/일일 요청 수가 작다. 본편 938면(현재 스캔 935장) × 블록 크롭을 한 번에 보내지 말고, 제공자별 quota를 DB에 기록하며 큐로 처리한다.
- **체크포인트**: `(image_sha256, prompt_version, page_id, block_id)` 단위로 결과를 저장해 중단점부터 이어간다.
- **캐시**: 같은 이미지/프롬프트는 재호출하지 않는다.
- **Fallback**: 한 제공자가 실패하면 다른 무료 제공자/로컬 PaddleOCR로 넘긴다.
- **데이터 정책**: 무료 API는 입력 데이터를 로그/학습에 사용할 수 있다. 문중 기록을 외부로 보내도 되는지 확인한다. 불가하면 로컬 OCR/로컬 VLM으로 전환한다.
- **비용 기록**: 무료라도 토큰/호출 수를 기록해 병목을 파악한다.

---

## 11. 사람 검수와의 연결

AI 출력은 바로 공개하지 않는다.

1. AI가 `draft`를 만든다.
2. 규칙 검증기가 오류/경고를 표시한다.
3. 검수자는 `confidence`가 낮은 항목, 관계 이상, `上###`/`下###` 불일치부터 확인한다.
4. 검수자가 승인한 항목만 `published`로 이동한다.
5. 모든 수정은 `review_actions`에 기록한다.

AI의 목표는 “완벽한 자동 추출”이 아니라 **사람이 검수할 수 있는 초안을 최소한의 비용으로 만드는 것**이다.
