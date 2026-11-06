FROM node:22-slim AS web
WORKDIR /build/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ARG INSTALL_RETRIEVAL=0
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY --from=web /build/src/aster/static ./src/aster/static
RUN if [ "$INSTALL_RETRIEVAL" = "1" ]; then \
      pip install --no-cache-dir torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu && \
      pip install --no-cache-dir '.[retrieval]'; \
    else pip install --no-cache-dir .; fi && \
    useradd --create-home --uid 1000 aster && mkdir /data && chown aster:aster /data
ENV ASTER_DATA_DIR=/data
USER aster
EXPOSE 8765
ENTRYPOINT ["aster"]
CMD ["--host", "127.0.0.1", "--port", "8765"]
