# Platform-deploy build of linkding, for Render/Railway/etc.
#
# This is identical to docker/default.Dockerfile up through the `linkding`
# stage, but omits the `linkding-plus` (Chromium/snapshot) stage. Platforms
# like Render and Railway build whatever Dockerfile they're pointed at using
# a plain `docker build` with no `--target` flag, which always builds the
# *last* stage in the file. Pointing them at docker/default.Dockerfile would
# therefore also build the extra `linkding-plus` stage (and its Chromium/
# uBlock download), even though only the plain `linkding` stage is needed.
#
# Keep this file in sync with docker/default.Dockerfile's `linkding` stage.
FROM node:22-alpine AS node-build
WORKDIR /etc/linkding
# install build dependencies
COPY rollup.config.mjs postcss.config.js package.json package-lock.json ./
RUN npm ci
# copy files needed for JS build
COPY bookmarks/frontend ./bookmarks/frontend
COPY bookmarks/styles ./bookmarks/styles
# run build
RUN npm run build


FROM python:3.13.7-slim-trixie AS build-deps
# Add required packages
# build-essential pkg-config: build Python packages from source
# libpq-dev: build Postgres client from source
# libicu-dev libsqlite3-dev: build Sqlite ICU extension
RUN apt-get update && apt-get -y install build-essential pkg-config libpq-dev libicu-dev libsqlite3-dev libffi-dev wget unzip
WORKDIR /etc/linkding
# install uv, use installer script for now as distroless images are not availabe for armv7
ADD https://astral.sh/uv/0.8.13/install.sh /uv-installer.sh
RUN chmod +x /uv-installer.sh && /uv-installer.sh
# install python dependencies
COPY pyproject.toml uv.lock ./
RUN /root/.local/bin/uv sync --no-dev --group postgres


FROM build-deps AS compile-icu
# Defines SQLite version
# Since this is only needed for downloading the header files this probably
# doesn't need to be up-to-date, assuming the SQLite APIs used by the ICU
# extension do not change
ARG SQLITE_RELEASE_YEAR=2023
ARG SQLITE_RELEASE=3430000

# Compile the ICU extension needed for case-insensitive search and ordering
# with SQLite. This does:
# - Download SQLite amalgamation for header files
# - Download ICU extension source file
# - Compile ICU extension
RUN wget https://www.sqlite.org/${SQLITE_RELEASE_YEAR}/sqlite-amalgamation-${SQLITE_RELEASE}.zip && \
    unzip sqlite-amalgamation-${SQLITE_RELEASE}.zip && \
    cp sqlite-amalgamation-${SQLITE_RELEASE}/sqlite3.h ./sqlite3.h && \
    cp sqlite-amalgamation-${SQLITE_RELEASE}/sqlite3ext.h ./sqlite3ext.h && \
    wget https://www.sqlite.org/src/raw/ext/icu/icu.c?name=91c021c7e3e8bbba286960810fa303295c622e323567b2e6def4ce58e4466e60 -O icu.c && \
    gcc -fPIC -shared icu.c `pkg-config --libs --cflags icu-uc icu-io` -o libicu.so


FROM python:3.13.7-slim-trixie AS linkding
LABEL org.opencontainers.image.source="https://github.com/sissbruecker/linkding"
# install runtime dependencies
RUN apt-get update && apt-get -y install media-types libpq-dev libicu-dev libssl3t64 curl
WORKDIR /etc/linkding
# copy python dependencies
COPY --from=build-deps /etc/linkding/.venv /etc/linkding/.venv
# copy output from node build
COPY --from=node-build /etc/linkding/bookmarks/static bookmarks/static/
# copy compiled icu extension
COPY --from=compile-icu /etc/linkding/libicu.so libicu.so
# copy application code
COPY . .
# Activate virtual env
ENV VIRTUAL_ENV=/etc/linkding/.venv
ENV PATH="/etc/linkding/.venv/bin:$PATH"
# Generate static files
RUN mkdir data && \
    python manage.py collectstatic

# Limit file descriptors used by uwsgi, see https://github.com/sissbruecker/linkding/issues/453
ENV UWSGI_MAX_FD=4096
# Expose uwsgi server at port 9090
EXPOSE 9090
# Allow running containers as an an arbitrary user in the root group, to support deployment scenarios like OpenShift, Podman
RUN chmod g+w . && \
    chmod +x ./bootstrap.sh

HEALTHCHECK --interval=30s --retries=3 --timeout=1s \
CMD curl -f http://localhost:${LD_SERVER_PORT:-${PORT:-9090}}/${LD_CONTEXT_PATH}health || exit 1

CMD ["./bootstrap.sh"]
