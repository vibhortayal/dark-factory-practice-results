FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /srv
COPY app.py /srv/app.py
EXPOSE 8080
CMD ["python", "/srv/app.py"]
