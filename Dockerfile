FROM python:3.12 as base

RUN touch /dummy-file-for-builder

RUN apt-get update && apt-get install -y fuse psmisc && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python3 -m pip --trusted-host pypi.org install -r requirements.txt
RUN rm requirements.txt

RUN mkdir -p /data/


FROM base AS devcontainer
COPY requirements-dev.txt .
RUN python3 -m pip --trusted-host pypi.org install -r requirements-dev.txt
RUN apt-get update && apt-get install -y entr


FROM base AS app

COPY src/*.py src/


FROM app as test

COPY requirements-dev.txt .
RUN python3 -m pip --trusted-host pypi.org install -r requirements-dev.txt
RUN isort --profile=black --check src/
RUN black --check --line-length=180 src/

# Test the script can run
RUN ["python3","-u","/app/src/solidfs.py","-h"]


FROM app AS runtime

COPY --from=test /dummy-file-for-builder /dummy-file-for-builder

ENTRYPOINT ["python3","-u","/app/src/solidfs.py","-d", "-f","-s", "/data/"]