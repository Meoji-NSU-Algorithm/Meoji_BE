FROM python:3.14-slim

# 로그를 버퍼 없이 바로 출력하고(docker logs에 즉시 보임), .pyc 파일은 만들지 않는다.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_APP=wsgi.py

WORKDIR /app

# requirements.txt만 먼저 복사해 설치한다. 코드만 바뀐 빌드에서는 이 층이 캐시된다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# root가 아닌 사용자로 실행한다. gunicorn이 홈 폴더에 제어 소켓을 만들므로 홈도 만든다.
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "--access-logfile", "-", "wsgi:app"]
