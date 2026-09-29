# Pocketful Stage 1: Build and Run Instructions

## Building the Docker Image

Build the Docker image using the provided Dockerfile:

```sh
docker build -t pocketful-stage-1 .
```

## Running the Service

Start the container with port mapping and environment variable:

```sh
docker run -e PORT=8080 -p 8080:8080 pocketful-stage-1
```

The service will:
1. Initialize the SQLite database at `/tmp/pocketful.db`
2. Listen on `0.0.0.0:8080` (or the port specified by PORT environment variable)
3. Return 200 OK on `GET /health` once ready (typically within 5-10 seconds)
4. Accept the first fixture via `POST /_test/reset`

## Verifying the Service

Once running, verify the service is healthy:

```sh
curl http://localhost:8080/health
```

Expected response:
```json
{"status": "ok"}
```

## API Endpoints

The service implements the complete Pocketful Stage 1 specification:

- **Authentication**: `/auth/signup`, `/auth/login`
- **User Info**: `GET /me`
- **Payments**: `POST /payments`, `GET /activity`
- **Requests**: `POST /requests`, `GET /requests`, `POST /requests/{id}/pay`, `POST /requests/{id}/decline`, `POST /requests/{id}/cancel`
- **Splits**: `POST /splits`
- **Settlements**: `POST /settlements`
- **Test Endpoints**: `POST /_test/reset`, `GET /_test/export`, `POST /_test/import`

All endpoints follow the API specification in the Stage 1 spec document.
