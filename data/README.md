# 독음 사전 데이터 출처

`name-readings.json`은 나무위키의 [인명용 한자](https://namu.wiki/w/인명용%20한자) 표를 사용자가 저장한 `docs/research/인명용한자.html`에서 기계적으로 변환한 자료다.

- 원문 라이선스: [CC BY-NC-SA 2.0 KR](https://creativecommons.org/licenses/by-nc-sa/2.0/kr/)
- 변경 내용: 음별 HTML 표를 한자별 독음 후보 JSON으로 역색인하고, 교육용·인명용·이체자 열을 `kinds`로 보존했다.
- 생성 명령: `.venv/bin/python scripts/build_name_readings.py`

이 라이선스의 저작자표시·비영리·동일조건변경허락 조건은 이 변환 데이터에 적용한다. 프로그램 코드는 별도 저작물이며, 이 파일은 현대 출생신고 가능 여부를 보증하는 법적 판정 자료가 아니다.
