# Standard library only: nothing to download at build or run time.
FROM python:3.12-slim
WORKDIR /app
COPY pocketful ./pocketful
ENV PORT=8080 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080
CMD ["python", "-m", "pocketful"]
