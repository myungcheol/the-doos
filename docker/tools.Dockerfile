# 테스트 도구 이미지: psql + python3
#
# 서버와 같은 psql 16을 쓰려고 PostgreSQL 공식 이미지를 베이스로 한다.
# Alpine에는 `postgresql-client` 메타 패키지가 없고 버전별 패키지
# (`postgresql16-client` 등)만 있어서, 버전이 어긋나지 않게 이쪽을 골랐다.

FROM postgres:16-alpine

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC

RUN apk add --no-cache python3 tzdata

WORKDIR /app

# PostgreSQL 엔트리포인트를 물려받지 않는다. 이 이미지는 도구 전용이다.
ENTRYPOINT []
CMD ["python3", "--version"]
