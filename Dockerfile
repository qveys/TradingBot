FROM python:3.12.16-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

WORKDIR /app
ENV PYTHONPATH=/app/src \
    PYTHONDONTWRITEBYTECODE=1

COPY src/tradingbot/ src/tradingbot/
USER 10001:10001
RUN python -m tradingbot.guard_image

EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s CMD ["python", "-c", "from http.client import HTTPConnection; c = HTTPConnection('127.0.0.1', 8080, timeout=2); c.request('POST', '/'); raise SystemExit(c.getresponse().status != 401)"]
CMD ["python", "-m", "tradingbot"]
