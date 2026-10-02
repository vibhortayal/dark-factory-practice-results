# Pocketful stage 2. Standard library only: nothing is fetched at run time.
FROM python:3.12-slim
WORKDIR /app
COPY app.py ./
COPY ui ./ui
ENV PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "-u", "app.py"]
