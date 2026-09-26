# the web app's docker image, built in 3 stages so the final image only has what it runs:
#   deps   installs the exact packages from package-lock.json
#   build  runs next build (output: "standalone" -> a small self-contained server)
#   run    copies just that server + static files, and runs it as a non-root user
#
# cloud run runs this image (build + push + deploy commands: CLAUDE.md section 10). it sets
# PORT=8080 itself, which overrides the PORT=3000 below.
#
# test it on the mac:  docker build -t fantano-web . && docker run -p 3000:3000 fantano-web

FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:24-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# no database needed here: every page that reads mysql renders per request (see src/lib/db.ts)
RUN npm run build

FROM node:24-alpine AS run
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
COPY --from=build /app/public ./public
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
# the node image comes with a "node" user; running as it means a bug in the app can't touch
# the rest of the container as root
USER node
EXPOSE 3000
CMD ["node", "server.js"]
