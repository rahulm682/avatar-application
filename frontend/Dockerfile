FROM node:22-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173

# Vite dev server with hot reload (the source is mounted by docker compose).
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
