FROM python:3.12

RUN apt-get update && apt-get install -y fuse psmisc && rm -rf /var/lib/apt/lists/*

# https://github.com/libfuse/python-fuse/
COPY requirements.txt .
RUN python3 -m pip --trusted-host pypi.org install -r requirements.txt

WORKDIR /app

COPY app_logging.py .
COPY cache.py .
COPY solidfs.py .
COPY solid_authentication.py .
COPY solid_request.py .
COPY solid_resource.py .

RUN mkdir -p /data/

# Test the script can run
RUN ["python3","-u","/app/solidfs.py","-h"]

ENTRYPOINT ["python3","-u","/app/solidfs.py","-d", "-f","-s", "/data/"]