FROM python:3.12-slim
WORKDIR /srv/app

# Stdlib HTTP; Pillow only to draw the cover collage.
RUN pip install --no-cache-dir pillow==11.*

COPY aicollections/ /srv/app/aicollections/
USER 1000:1000
ENTRYPOINT ["python", "-m", "aicollections"]
