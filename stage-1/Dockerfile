# Standard library only: nothing is fetched at build or run time besides the base image.
FROM python:3.12-slim
WORKDIR /app
COPY app.py ./
ENV PORT=8080 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080
CMD ["python", "-u", "app.py"]
