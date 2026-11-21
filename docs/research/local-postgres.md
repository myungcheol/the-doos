# T014 로컬 PostgreSQL 운영

`compose.yaml`은 PostgreSQL만 실행한다. 프로젝트명 `jokbo-local`, 볼륨 `jokbo-local_postgres-data`를 사용한다. 기존 로컬 컨테이너와 볼륨이 이미 있으면 그대로 재사용한다. 웹과 OCR은 이 Compose에 포함하지 않는다.

## 처음 시작할 때

`.env.postgres.example`의 PostgreSQL 항목을 `.env`에 복사하고 비밀번호를 직접 정한다. `.env`는 Git 추적 대상이 아니다. 이미 `.env`에 `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`가 있으면 그 설정을 유지한다. 데이터가 들어 있는 볼륨에서는 환경 변수의 비밀번호를 바꿔도 기존 DB 계정 비밀번호가 자동 변경되지 않는다.

```bash
docker compose config --quiet
docker compose up -d --no-recreate postgres
docker compose ps
```

새로운 컴퓨터에서 최초 실행한다면 `--no-recreate`는 없어도 된다. `127.0.0.1:${POSTGRES_PORT:-5432}`에만 포트를 열며 외부 네트워크에는 노출하지 않는다.

## 상태·중지·재시작

```bash
docker compose ps
docker compose exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose stop postgres
docker compose start postgres
```

`docker compose stop`은 데이터를 지우지 않는다. 현재 로컬 볼륨은 프로젝트 데이터이므로 `docker compose down -v` 또는 `docker volume rm`을 실행하지 않는다. 다른 프로젝트에 DB를 배포할 때는 별도 백업·복원을 계획한다.

연결 문자열은 애플리케이션 환경 설정에 두며 저장소에 커밋하지 않는다. 사용자·DB 이름·비밀번호에 특수 문자가 있으면 URL 인코딩해서 사용한다. DB 스키마 생성은 다음 티켓부터 진행한다.
