# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

# OpenAN Registry Center Container Image
# Multi-stage build for OpenShift / Kubernetes deployment.
#
# Build:
#   podman build -t registry-center:latest .
#
# Mount deployment certificates/configuration at runtime, never at build time.
# See docs/container-deployment.md for secure and local-development examples.
# `init` validates preconfigured settings without stdin; it does not issue certs.

FROM python:3.12-slim AS builder

USER root

# Install build dependencies for packages that may need compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc6-dev \
    libpq-dev \
    libssl-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt

RUN python3 -m venv /opt/venv --copies \
    && . /opt/venv/bin/activate \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm -rf /tmp/requirements.txt /root/.cache/pip

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends bash libpq5 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

# Image defaults, applied on every start. The REGISTRY_* entries are read by
# common/util/app_config.py, which maps REGISTRY_FOO_BAR onto the config key
# foo.bar (or foobar) after server.conf and server.properties are loaded, so an
# operator can override any of them with -e / --env at run time.
#   PYTHONUNBUFFERED=1                  stream logs immediately under journal/docker
#   REGISTRY_IP=0.0.0.0                 listen on all interfaces; server.conf ships 127.0.0.1
#   REGISTRY_PORT=8080                  matches EXPOSE below; server.conf ships 5000.
#                                       PORT (Cloud Run) wins over it in the entrypoint
#   REGISTRY_ENABLE_HTTPS=true          TLS on the main listener; certificates must be mounted
#   REGISTRY_VERIFY_CLIENT=true         require an mTLS client certificate
#   REGISTRY_OWNER_ISOLATION_ENABLED=true  enforce AgentCard ownership
#   REGISTRY_FORWARDED_ALLOW_IPS        trusted proxy for X-Forwarded-*; bare value,
#                                       no quotes, "empty" means trust no proxy
#   REGISTRY_STARTUP_STRICT_IDENTITY=true  refuse to serve when no caller identity can be
#                                       verified (exits before binding the port)
# No owner-mode variable is baked in, so a deployment that sets
# REGISTRY_OWNER_VALIDATION_MODE=strict is never masked by an image default.
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    REGISTRY_IP=0.0.0.0 \
    REGISTRY_PORT=8080 \
    REGISTRY_ENABLE_HTTPS=true \
    REGISTRY_VERIFY_CLIENT=true \
    REGISTRY_OWNER_ISOLATION_ENABLED=true \
    REGISTRY_FORWARDED_ALLOW_IPS="127.0.0.1" \
    REGISTRY_STARTUP_STRICT_IDENTITY=true

# An allowlist is a second boundary in addition to .dockerignore. Public
# templates, not the developer's mutable deployment files, seed the image.
COPY agent_registry/ /opt/registry-center/agent_registry/
COPY common/ /opt/registry-center/common/
COPY bin/entrypoint.sh /opt/registry-center/bin/entrypoint.sh
# Runtime configuration shipped in the image (the examples are copied to their
# live filenames; the Python applies environment overrides without rewriting them):
#   etc/conf/server.conf        <- server.conf.example (IP, PORT, enable_https,
#                                  forwarded_allow_ips, owner.validation.mode)
#   etc/conf/persistence.conf   <- persistence.conf.example (persistence.mode, DB_*)
#   etc/conf/server.properties  operating parameters and business policies
#   etc/conf/log_config.conf    audit log rotation
# Deliberately NOT in the image; provide them by mounting, or they keep their
# built-in defaults:
#   etc/conf/integration_credentials.conf  (static Bearer / mTLS entries; excluded by
#                                           .dockerignore, so it cannot be a build input)
#   etc/config/models.yaml                 (LLM model definitions; the entrypoint can
#                                           generate a chat-only file from LLM_CHAT_*)
#   etc/conf/custom_openssl.cnf            (TLS group policy; the systemd unit sets
#                                           OPENSSL_CONF to it, the container does not)
#   etc/ssl/*                              (server.cer, server_key.pem, cert_pwd, trust.cer)
COPY etc/conf/server.conf.example /opt/registry-center/etc/conf/server.conf
COPY etc/conf/server.conf.example /opt/registry-center/etc/conf/server.conf.example
COPY etc/conf/persistence.conf.example /opt/registry-center/etc/conf/persistence.conf
COPY etc/conf/db/ /opt/registry-center/etc/conf/db/
COPY etc/conf/server.properties etc/conf/log_config.conf /opt/registry-center/etc/conf/

RUN useradd --uid 10001 -m appuser \
    && ln -sf /opt/registry-center /opt/app \
    && mkdir -p /opt/registry-center/log /opt/registry-center/run /opt/registry-center/data \
    && mkdir -p /opt/registry-center/etc/ssl /opt/registry-center/etc/sign_cert \
    && sed -i 's/\r$//' /opt/registry-center/bin/entrypoint.sh \
    && chmod 0755 /opt/registry-center/bin/entrypoint.sh \
    && chmod 0600 /opt/registry-center/etc/conf/*.conf \
    && chmod 0700 /opt/registry-center/etc/ssl /opt/registry-center/etc/sign_cert \
    && chown -R appuser:appuser /opt/registry-center /opt/venv

# Runtime facts an operator depends on:
#   - WORKDIR is the installation root, so relative paths in server.conf
#     (etc/ssl/..., etc/conf/cipher.key) resolve as documented.
#   - The service runs as the unprivileged user appuser (UID 10001); mounted
#     certificates, config and data directories must be readable by that UID and
#     runtime model files may be mounted read-only.
#   - The image carries no cipher key, certificate or credential file: supply
#     etc/ssl/*, etc/config/models.yaml and
#     etc/conf/integration_credentials.conf at run time.
WORKDIR /opt/registry-center

USER appuser

# Matches the REGISTRY_PORT default above; Cloud Run's PORT overrides it at run
# time through bin/entrypoint.sh.
EXPOSE 8080

# No argument is required: with an empty command the entrypoint runs "serve".
# "init" runs the non-interactive configuration validation instead.
ENTRYPOINT ["/opt/registry-center/bin/entrypoint.sh"]
CMD ["serve"]
