# RUN.md

To build and run the pocketful service, execute the following commands in the `stage-1` directory:

```bash
docker build -t pocketful-stage1 .
docker run -p 8080:8080 -e PORT=8080 pocketful-stage1
```
