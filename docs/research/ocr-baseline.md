# T005 단일 페이지 OCR 기준선

- 실행일: 2026-11-18. 입력 `scan/genealogy/001.jpg`, Python 3.12.15, Linux x86_64 CPU.
- PaddleOCR 3.3.1, PaddlePaddle 3.2.0, PaddleX 3.3.13. 공식 `PP-OCRv5_mobile_det`, `PP-OCRv5_mobile_rec` 모델; 문서 방향·왜곡 보정과 글줄 방향 분류는 끔. 인식 점수 필터는 0.
- 첫 실행: 모델 다운로드 후 초기화 4.452초, 추론 3.158초. 기기와 모델 캐시 상태에 따라 다르다. 검출·인식된 영역 104개.
- T004의 확인 표본에 대해 `景吉`은 문자열에 포함되었다. `景斗`는 `景升`으로, `下2`, `下3`은 각각 `F2`, `F3`으로 나왔다. 이는 일부 사례의 직접 확인이며 전체 문자 정확도 수치는 아니다.
- 페이지 전체를 입력한 기준선이다. 작은 글자와 세로 배치가 섞여 있고 읽기 순서도 족보 순서와 다르므로 이 결과만으로 관계를 확정할 수 없다. T006에서 열 전처리를 검토한다. T004 좌표는 초안이므로 영역 IoU 측정에 사용하지 않았다.
- CLI 출력의 다각형은 입력 이미지 좌상단을 원점으로 하는 픽셀 좌표다. 점수는 모델의 인식 신뢰도이며 정답 확률로 보장되지 않는다. 모델명과 상위 패키지 버전을 고정했으나 간접 의존성 및 내려받은 모델 파일 해시까지 고정한 환경은 아니다.
- 참고: [PaddleOCR 실행 안내](https://www.paddleocr.ai/v3.3.1/en/quick_start.html), [OCR 결과 필드](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html).

## `chinese_cht` 설정 재실행

- 사용자 요청으로 `lang=chinese_cht`, `ocr_version=PP-OCRv5`, `device=cpu`를 명시했다. PaddleOCR 3.3.1은 이 조합에 `PP-OCRv5_server_det`, `PP-OCRv5_server_rec`을 선택한다. 이전 mobile 모델과 다르므로 언어 설정만의 효과로 해석할 수 없다. 기존 mobile 인식 모델도 번체 한자를 지원한다.
- 동일한 001쪽 전체 입력: 105개 영역, 추론 20.103초. `景吉`과 `下2`를 인식했고 `景斗`는 `景升`, `下3`은 `F3`으로 읽었다. 이전 mobile 전체 페이지 실행은 104개 영역, 3.158초, `下2`도 `F2`로 읽었다.
- 002쪽 전체 입력: 103개 영역, 추론 14.642초. `景吉`, `子應龍`이 포함되었다. 기존 mobile 실행은 87개 영역이며 두 이름 모두 포함됐다. 초기화 및 추론 시간은 환경과 캐시 상태에 따라 변한다.
- 결과는 각각 `/tmp/the-doos-ocr-001-cht.json`, `/tmp/the-doos-ocr-002-cht.json`에 임시 저장했다. 전체 정확도를 측정한 결과는 아니다.
- 모델 선택과 번체 지원 참고: [PaddleOCR 3.3.0 인식 모델 문서](https://www.paddleocr.ai/v3.3.0/en/version3.x/module_usage/text_recognition.html).
