FROM node:20-alpine
WORKDIR /app
COPY package.json server.js ./
ENV PORT=8080 NODE_ENV=production
EXPOSE 8080
USER node
CMD ["node", "server.js"]
