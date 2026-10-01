FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
WORKDIR /app
COPY server.py /app/server.py
EXPOSE 8080
CMD ["python", "-u", "/app/server.py"]
