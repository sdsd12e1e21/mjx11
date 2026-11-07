FROM quay.io/sclorg/python-312-c9s@sha256:1185c4593a4f739d06cb0d4f9d34cbf11e1792b0c0ca708078bb4dcd430bd862
USER 0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1
RUN dnf -y install iproute util-linux && dnf clean all
COPY requirements-linux.lock /tmp/requirements-linux.lock
RUN python3 -m venv /opt/sdd-venv && /opt/sdd-venv/bin/pip install --no-cache-dir -r /tmp/requirements-linux.lock
ENV PATH="/opt/sdd-venv/bin:$PATH" PYTHONPATH=/app/src PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
WORKDIR /app
COPY . /app
RUN /opt/sdd-venv/bin/pip install --no-cache-dir --no-deps /app
COPY docker/entrypoint.sh /usr/local/bin/sdd-entrypoint
ENTRYPOINT ["/bin/sh", "/usr/local/bin/sdd-entrypoint"]
CMD ["python", "-m", "minimax_sdd", "versions"]
