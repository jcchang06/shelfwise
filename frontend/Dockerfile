# Development image (vite dev server). Production is a Render static site built with `npm run build`.
FROM node:22-alpine

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]
