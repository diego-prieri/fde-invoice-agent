FROM python:3.12-slim
WORKDIR /app
# Fuente con tildes para renderizar los comprobantes degradados (datagen --degrade)
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir ".[claude,images]"
EXPOSE 8000
CMD ["uvicorn", "invoice_agent.mock_erp.app:app", "--host", "0.0.0.0", "--port", "8000"]
