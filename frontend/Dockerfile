FROM node:22-alpine AS dev
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]

# ---------------------------------------------------------------------------
# Production. Three stages so the final image carries neither the toolchain nor
# a full node_modules — only the standalone server Next emits.
# ---------------------------------------------------------------------------

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Load-bearing at *build* time, not just runtime: `rewrites()` in
# next.config.ts is evaluated by `next build` and the result is frozen into
# .next/routes-manifest.json. Setting this only in compose would bake the
# localhost fallback into the image and every /api/* call would 502 in
# production. The default matches the service name on the compose network.
ARG API_URL=http://api:8000
ENV API_URL=$API_URL

# Compiled into the client bundle, so it must be present now — changing it
# later needs a rebuild, not a restart.
ARG NEXT_PUBLIC_VAPID_PUBLIC_KEY=
ENV NEXT_PUBLIC_VAPID_PUBLIC_KEY=$NEXT_PUBLIC_VAPID_PUBLIC_KEY

RUN npm run build

FROM node:22-alpine AS prod
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Standalone bundles the server but deliberately leaves these two behind, so
# they are copied separately. Missing `public` is what silently breaks the PWA:
# no sw.js means no offline reading, no install prompt, no push.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public

RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001 -G nodejs
USER nextjs

EXPOSE 3000
CMD ["node", "server.js"]
