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

COPY app_logging.py .
COPY cache.py .
COPY solidfs.py .
COPY solid_authentication.py .
COPY solid_request.py .
COPY solid_resource.py .
COPY solidfs_resource_hierarchy.py .

# Test the script can run
RUN ["python3","-u","/app/solidfs.py","-h"]

ENTRYPOINT ["python3","-u","/app/solidfs.py","-d", "-f","-s", "/data/"]