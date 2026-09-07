# CI Agent API — modular monolith (§4). Ships with pinned OSS CLIs it wraps:
# actionlint (validation), syft (SBOM), cosign (signing). Each has a version
# ARG and a latest-release fallback so the build never breaks on a yank.
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

ARG ACTIONLINT_VERSION=v1.7.7
ARG SYFT_VERSION=v1.21.0
ARG COSIGN_VERSION=v2.4.3

RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl ca-certificates openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && arch=$$(dpkg --print-architecture) \
    # --- actionlint (assets use linux_amd64 / linux_arm64) ---
    && ( curl -sSfL -o /tmp/actionlint.tar.gz \
           "https://github.com/rhysd/actionlint/releases/download/${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION#v}_linux_$${arch}.tar.gz" \
         || ( ver=$$(curl -sSfL https://api.github.com/repos/rhysd/actionlint/releases/latest | grep '"tag_name"' | cut -d'"' -f4) \
              && curl -sSfL -o /tmp/actionlint.tar.gz \
                   "https://github.com/rhysd/actionlint/releases/download/$${ver}/actionlint_$${ver#v}_linux_$${arch}.tar.gz" ) ) \
    && tar -xzf /tmp/actionlint.tar.gz -C /usr/local/bin actionlint \
    && chmod +x /usr/local/bin/actionlint \
    # --- syft ---
    && ( curl -sSfL -o /tmp/syft.tar.gz \
           "https://github.com/anchore/syft/releases/download/${SYFT_VERSION}/syft_${SYFT_VERSION#v}_linux_$$(dpkg --print-architecture).tar.gz" \
         || curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/scripts/install.sh | sh -s -- -b /usr/local/bin ) \
    && ( tar -xzf /tmp/syft.tar.gz -C /usr/local/bin syft 2>/dev/null || true ) \
    && chmod +x /usr/local/bin/syft 2>/dev/null || true \
    # --- cosign ---
    && ( curl -sSfL -o /usr/local/bin/cosign \
           "https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}/cosign-linux-$$(dpkg --print-architecture)" \
         || ( ver=$$(curl -sSfL https://api.github.com/repos/sigstore/cosign/releases/latest | grep '"tag_name"' | cut -d'"' -f4) \
              && curl -sSfL -o /usr/local/bin/cosign \
                   "https://github.com/sigstore/cosign/releases/download/$${ver}/cosign-linux-$$(dpkg --print-architecture)" ) ) \
    && chmod +x /usr/local/bin/cosign \
    && rm -f /tmp/*.tar.gz \
    && useradd --create-home --uid 10001 ciagent \
    && mkdir -p /var/lib/ci-agent/work /var/lib/ci-agent/data /app \
    && chown -R ciagent:ciagent /var/lib/ci-agent /app

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

ENV CI_AGENT_DATA_DIR=/var/lib/ci-agent/data \
    AGENT_WORK_DIR=/var/lib/ci-agent/work \
    PATH=/app/src:$PATH \
    PYTHONPATH=/app/src:$PYTHONPATH

USER ciagent
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz').read()" || exit 1
CMD ["uvicorn", "ci_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
