FROM node:20-alpine
ENV NODE_ENV=production
WORKDIR /app
COPY package.json ./
COPY src ./src
COPY public ./public
COPY test ./test
EXPOSE 8080
USER node
CMD ["node", "src/index.js"]
