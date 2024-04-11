# SolidFS

SolidFS is a [FUSE](https://github.com/libfuse/libfuse) driver for [Solid](https://solidproject.org/).

It is very limited in what it can support but is able to interact with Pods.

Some of the limitations are:
1. shortcomings in this code
2. related to server implementations
3. related to the current Solid specification

There is no plan to resolve any one of the specific shortcomings at 2024-04-11.

## Running

It's currently very hard to run this.

We're assuming you are mounting your Solid Pod at `/data/`.

### Python

You may be successful with:
1. a suitable Python environment with the [requirements](requirements.txt)
2. set the environment variables mentioned in [.env.sample](.env.sample)
3. python3 solidfs.py -fd /data/

### Docker

```bash
docker \
  build \
  -t solidfs \
  -f .devcontainer/Dockerfile \
  .
```

```bash
docker run \
  --rm \
  --cap-add=SYS_ADMIN \
  --device=/dev/fuse \
  --name solidfs \
  -v $(pwd)/:/data/:rshared \
  --env-file ${HOME}/.env \
  solidfs \
 -fd /data/
```

## Using

### Simple Listing

Start off gently:

```bash
ls -lh /data/
```
You may see some output like this:
```
total 0
drwx------. 2 root root 0 Jul 20  2022 bookmarks
drwx------. 2 root root 0 Jul 23  2022 contacts
drwx------. 2 root root 0 Jul 20  2022 inbox
drwx------. 2 root root 0 Jul 20  2022 policies
drwx------. 2 root root 0 Jul 20  2022 private
drwx------. 2 root root 0 Apr  9 18:40 profile
drwx------. 2 root root 0 Jul 20  2022 settings
```

### Delving into the Filesystem

Being more adventerous:

```bash
find /data/test/bob/
```
In my Pod this returns:
```
/data/test/bob/
/data/test/bob/b2o🐝
/data/test/bob/b2o🐝/🦖
/data/test/bob/b2o🐝/🦖/🦢
/data/test/bob/b2o🐝/🦖/🦢/test.html
/data/test/bob/b2o🐝/🦖/🦢/date2.txt
/data/test/bob/b2o🐝/🦖/🦢/date3.txt
/data/test/bob/b2o🐝/🦖/🦢/date4.txt
/data/test/bob/b2o🐝/🦖/🦢/card.ttl
/data/test/bob/b2o🐝/🦖/🦢/🌳
```

### Using Powerful Tools

Here I'm using an existing tool to push some content up to my Pod without writing any new code:

```bash
rsync -av weather/2023/2023-04 solid/weather/
```

```
sending incremental file list
2023-04/
2023-04/2023-04-01.txt
2023-04/2023-04-02.txt
2023-04/2023-04-03.txt
...
2023-04/2023-04-29.txt
2023-04/2023-04-30.txt

sent 606,817 bytes  received 590 bytes  3,480.84 bytes/sec
total size is 604,760  speedup is 1.00
```

Cleaning up:

```bash
rm -rf solid/weather/
```

Here I'm looking for something in a file:

```bash
# grep name solid/profile/card
vcard:organization-name  "MyForest" ;
foaf:name                "MyForest 🦆" .
```

Here is a graphical tool using the file system mount:

 ![Visual Studio Code showing a Pod](docs/pod_in_vscode.png)

## Developing

There is no guidance on this yet.


## Testing

With a Pod mounted at `/data/` run:

```bash
pytest -n auto test.py
```
```
========================================== test session starts ==========================================
platform linux -- Python 3.12.2, pytest-8.1.1, pluggy-1.4.0
rootdir: /workspaces/SolidFS
configfile: pytest.ini
plugins: xdist-3.5.0
16 workers [17 items]     
.................                                                                                 [100%]
========================================== 17 passed in 12.37s ==========================================
```

## Similar Projects

### Visual Studio Code Extension solidFS

[Jesse Wright](https://github.com/jeswr) has had a [solidFS](https://marketplace.visualstudio.com/items?itemName=jeswr.solidfs) extension for VSCode for a while. We agreed there won't be confusion because SolidFS will never be a VSCode extension. Despite the similar names David Bowen opted for "SolidFS" to align with [other FUSE driver naming](https://en.wikipedia.org/wiki/Filesystem_in_Userspace#Remote/distributed_file_system_clients).

### Solid File Client

There are a number of [Solid apps](https://solidproject.org/apps), for example Jeff Zucker's [solid-file-client](https://github.com/jeff-zucker/solid-file-client) can be used to do many of the things SolidFS would do, but solid-file-client has Solid-focused parts such as specifying the content type for files which can't be done using normal file interactions via FUSE.

### bash-like Functions for Solid

SolidLab have a [bashlib](https://github.com/SolidLabResearch/Bashlib/) tool which uses TypeScript to implement the file management functions. By using custom commands it provides more options on each command than you get with SolidFS.