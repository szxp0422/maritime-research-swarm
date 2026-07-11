FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x start.sh

EXPOSE 8080

# Single-element exec-form CMD on purpose: Maritime's launcher was observed
# mis-splitting a multi-word shell-form CMD (each word became a separate
# argv item to `sh -c`, so only the first word ran and the rest were
# dropped as unused positional params). A single script path has nothing
# to mis-split. start.sh resolves Maritime's injected PORT internally.
CMD ["./start.sh"]