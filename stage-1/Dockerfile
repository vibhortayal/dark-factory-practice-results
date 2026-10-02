FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN pip install --no-cache-dir tzdata==2025.2
WORKDIR /srv
COPY app ./app
ENV PORT=8080
EXPOSE 8080
CMD ["python", "-m", "app"]
