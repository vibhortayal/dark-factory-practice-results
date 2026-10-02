# Pure standard-library Python service: no runtime dependencies, no network needed at run time.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
WORKDIR /srv
COPY app ./app
EXPOSE 8080
CMD ["python", "-m", "app.main"]
