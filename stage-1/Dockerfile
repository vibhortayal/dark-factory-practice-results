FROM node:20-alpine
ENV NODE_ENV=production
WORKDIR /app
COPY package.json server.js ./
EXPOSE 8080
USER node
CMD ["node", "--max-old-space-size=1280", "server.js"]
