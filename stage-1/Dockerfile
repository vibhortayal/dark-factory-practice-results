FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY app.py /app/app.py
EXPOSE 8080
USER nobody
CMD ["python", "/app/app.py"]
