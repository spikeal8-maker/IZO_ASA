FROM debian:bookworm-slim@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171

ARG DEBIAN_FRONTEND=noninteractive
ARG CA_CERTIFICATES_VERSION=20250419~deb12u1
ARG GIT_VERSION=1:2.39.5-0+deb12u3
ARG OPENSSH_CLIENT_VERSION=1:9.2p1-2+deb12u10
ARG PYTHON3_VERSION=3.11.2-1+b1
ARG PYTHON3_PIP_VERSION=23.0.1+dfsg-1
ARG PYTHON3_VENV_VERSION=3.11.2-1+b1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ca-certificates=${CA_CERTIFICATES_VERSION} \
       git=${GIT_VERSION} \
       openssh-client=${OPENSSH_CLIENT_VERSION} \
       python3=${PYTHON3_VERSION} \
       python3-pip=${PYTHON3_PIP_VERSION} \
       python3-venv=${PYTHON3_VENV_VERSION} \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --uid 10001 --create-home --shell /bin/sh agent \
    && mkdir -p /workspace /run/izo-ssh \
    && chown agent:agent /workspace

COPY entrypoint.sh /usr/local/bin/izo-agent-entrypoint
COPY boundary-probe.sh /usr/local/bin/izo-agent-boundary-probe

RUN sed -i 's/\r$//' \
    /usr/local/bin/izo-agent-entrypoint \
    /usr/local/bin/izo-agent-boundary-probe \
    && chmod 0755 \
    /usr/local/bin/izo-agent-entrypoint \
    /usr/local/bin/izo-agent-boundary-probe

USER 10001:10001
WORKDIR /workspace

ENV HOME=/home/agent \
    GIT_TERMINAL_PROMPT=0 \
    GIT_CONFIG_NOSYSTEM=1

ENTRYPOINT ["/usr/local/bin/izo-agent-entrypoint"]
CMD ["sh"]
