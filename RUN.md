# Pocketful Service - Build and Run

## Quick Start

### Build the Docker image:
```bash
docker build -t pocketful .
```

### Run the service:
```bash
docker run -e PORT=8080 -p 8080:8080 pocketful
```

The service will start and listen on `0.0.0.0:8080` (or whatever PORT you specify).

## Health Check

Once the container is running, verify it's ready:
```bash
curl http://localhost:8080/health
```

Expected response:
```json
{"status": "ok"}
```

## Environment Variables

- `PORT` (default: `8080`) - Port to listen on

## Resource Requirements

- CPU: 2 vCPU
- Memory: 2 GiB
- Startup time: < 60 seconds
- Per-request timeout: 5 seconds (10 seconds for reset)

## Development

To build and run locally without Docker:

```bash
npm install
npm run build
npm start
```

Or with ts-node for development:
```bash
npm install
npm run dev
```
