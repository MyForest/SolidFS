FROM python:3.12 as base

RUN touch /dummy-file-for-builder

RUN apt-get update && apt-get install -y fuse && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV SOLIDFS_ENABLE_WEBSOCKET_NOTIFICATIONS=1
ENV SOLIDFS_CONTENT_CACHING=1
ENV SOLIDFS_HTTP_LIBRARY=requests

COPY requirements.txt .
RUN python3 -m pip --trusted-host pypi.org install -r requirements.txt
RUN rm requirements.txt

RUN mkdir -p /data/


FROM base AS devcontainer
COPY requirements-dev.txt .
RUN python3 -m pip --trusted-host pypi.org install -r requirements-dev.txt
RUN apt-get update && apt-get install -y entr psmisc exa

# Do not copy content such as Python source files because the latest files will be available in the development environment

FROM base AS app

COPY LICENCE .
COPY README.md .
COPY src/ src/
COPY pyproject.toml .

FROM base as test

COPY requirements-dev.txt .
RUN python3 -m pip --trusted-host pypi.org install -r requirements-dev.txt

# Don't use "app" as the FROM for testing because that causes a re-install of the dev dependencies every time
COPY --from=app /app /app

RUN isort --check src/
RUN black --check src/

# Test the script can run
RUN ["python3","-u","/app/src/solidfs.py","-h"]


FROM app AS runtime

COPY --from=test /dummy-file-for-builder /dummy-file-for-builder

ENTRYPOINT ["python3","-u","/app/src/solidfs.py","-d", "-f","-s", "/data/"]