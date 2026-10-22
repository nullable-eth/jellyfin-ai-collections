FROM python:3.12-slim
# eMudhra CA compromise (20 Oct 26): eight eMudhra intermediate keys are
# derivable from their certificates. Take the distro's fixed ca-certificates
# even when the base image predates it.
RUN apt-get update && apt-get install -y --no-install-recommends --only-upgrade ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/app

# Stdlib HTTP; Pillow only to draw the cover collage.
RUN pip install --no-cache-dir pillow==11.*

COPY aicollections/ /srv/app/aicollections/
# certifi >= 2026.10.19 drops the compromised roots; requests/httpx use it,
# not the OS store.
RUN pip install --no-cache-dir -U "certifi>=2026.10.19"

USER 1000:1000
ENTRYPOINT ["python", "-m", "aicollections"]
