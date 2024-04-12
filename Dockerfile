FROM python:3.12 as base

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

FROM base AS runtime

COPY src/*.py src/

# Test the script can run
RUN ["python3","-u","/app/src/solidfs.py","-h"]

ENTRYPOINT ["python3","-u","/app/src/solidfs.py","-d", "-f","-s", "/data/"]