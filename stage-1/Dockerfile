FROM node:20-alpine
WORKDIR /app
COPY package.json server.js ./
ENV PORT=8080 UV_THREADPOOL_SIZE=2
EXPOSE 8080
USER node
CMD ["node", "server.js"]
