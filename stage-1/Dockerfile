FROM node:20-alpine
ENV NODE_ENV=production \
    NODE_OPTIONS=--max-old-space-size=1536 \
    UV_THREADPOOL_SIZE=2
WORKDIR /app
COPY package.json ./
COPY src ./src
USER node
EXPOSE 8080
CMD ["node", "src/server.js"]
