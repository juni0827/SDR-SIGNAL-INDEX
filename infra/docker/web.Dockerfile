FROM node:22-alpine AS build
WORKDIR /app
ARG SIGNAL_INDEX_API_PROXY=http://api:8000/api/v1
ENV SIGNAL_INDEX_API_PROXY=$SIGNAL_INDEX_API_PROXY NEXT_TELEMETRY_DISABLED=1
COPY package.json ./
COPY apps/web/package.json apps/web/package.json
RUN npm install
COPY apps/web apps/web
RUN npm run build --workspace=@signal-index/web

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/apps/web ./apps/web
COPY package.json ./
USER node
EXPOSE 3000
CMD ["npm", "run", "start", "--workspace=@signal-index/web"]
