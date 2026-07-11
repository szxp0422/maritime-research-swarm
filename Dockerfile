FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# Shell form (not exec/JSON form) so ${PORT} gets substituted at runtime.
# Maritime injects its own PORT env var and forwards its public port to it;
# hardcoding 8080 here collides with Maritime's own forwarder on that port.
# Falls back to 8080 for local `docker run` / plain `uvicorn` use.
CMD uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080}