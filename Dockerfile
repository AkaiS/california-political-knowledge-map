# Official Community distribution pins Neo4j and its compatible Java runtime.
FROM ghcr.io/astral-sh/uv:0.12.21@sha256:a7aed3216253ee804de3e2d8afa5073baa1a177335345d43845cd4165e43b711 AS uv
FROM neo4j:2026.07.1@sha256:dca31d0d938dd8bb199c8846abedd897c3a07ddb629eca46a8009ac9e87aece2 AS llama-build
USER root
RUN apt-get update && apt-get install -y --no-install-recommends git cmake make gcc g++ ca-certificates && rm -rf /var/lib/apt/lists/*
RUN git init /llama && cd /llama && git remote add origin https://github.com/ggml-org/llama.cpp.git && git fetch --depth 1 origin dee2a846b82f15d27f84a48fa387cb53e0d99c25 && git checkout --detach FETCH_HEAD
# Generic CPU instructions allow the same release on the hosted architecture.
RUN cmake -S /llama -B /llama/build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF -DLLAMA_CURL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=ON && cmake --build /llama/build --target llama-server --parallel 1

FROM neo4j:2026.07.1@sha256:dca31d0d938dd8bb199c8846abedd897c3a07ddb629eca46a8009ac9e87aece2
USER root
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=llama-build /llama/build/bin/llama-server /usr/local/bin/llama-server
ENV UV_PYTHON_INSTALL_DIR=/opt/python UV_PYTHON_PREFERENCE=only-managed UV_LINK_MODE=copy UV_NO_CACHE=1
RUN uv python install 3.13.5
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY classifier/pyproject.toml classifier/pyproject.toml
COPY classifier/src classifier/src
COPY src src
COPY deployment deployment
RUN uv sync --locked --no-dev --group deployment --python 3.13.5 && chown -R neo4j:neo4j /app /opt/python
ARG APP_REVISION=unknown
ENV BUILD_REVISION=${APP_REVISION} NEO4J_VERSION=2026.07.1 DEPLOYMENT_ENVIRONMENT=production CHAT_DEPLOYMENT=openrouter
RUN uv run --no-sync --python 3.13.5 deployment/build_metadata.py
LABEL org.opencontainers.image.revision=${APP_REVISION}
# Bottle uses rootless Podman. UID 0 maps to its host account and can write the
# injected, idmapped persistence directory without changing host ownership.
USER root
EXPOSE 8080
ENTRYPOINT ["uv", "run", "--no-sync", "--python", "3.13.5", "-m", "knowledge_map.cloud_runtime"]
CMD ["bootstrap"]
