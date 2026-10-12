"""Docker container lifecycle for coding jobs. The docker SDK is blocking, so every call runs in a thread."""
import asyncio
import io
import tarfile
import time

import docker

from apps.config import SANDBOX_IMAGE

_client = None


def _docker():
    global _client
    if _client is None:
        _client = docker.from_env()
    return _client


class SandboxError(Exception):
    def __init__(self, message, output=""):
        super().__init__(message)
        self.output = output  # full command output, for traces


async def start():
    return await asyncio.to_thread(_docker().containers.run, SANDBOX_IMAGE, detach=True, mem_limit="4g")


async def exec(container, cmd, env=None, workdir="/work"):
    """Run a shell command in the container; returns its output, raises SandboxError on a non-zero exit."""
    result = await asyncio.to_thread(
        container.exec_run, ["bash", "-lc", cmd], environment=env, workdir=workdir, user="agent"
    )
    output = result.output.decode(errors="replace")
    if result.exit_code != 0:
        raise SandboxError(f"`{cmd.split()[0]}` exited with {result.exit_code}:\n{output[-3000:]}", output)
    return output


async def put_file(container, path, content):
    """Write a file into the container, owned by the agent user."""
    directory, name = path.rsplit("/", 1)
    data = content.encode()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mtime = int(time.time())
        info.uname = info.gname = "agent"
        info.uid = info.gid = 1001
        info.mode = 0o600
        tar.addfile(info, io.BytesIO(data))
    await exec(container, f"mkdir -p {directory}", workdir="/")
    await asyncio.to_thread(container.put_archive, directory, archive.getvalue())


async def fetch_dir(container, path, dest):
    """Copy a directory out of the container into local `dest`. Returns False if it doesn't exist."""

    def _fetch():
        try:
            stream, _ = container.get_archive(path)
        except docker.errors.NotFound:
            return False
        archive = io.BytesIO(b"".join(stream))
        with tarfile.open(fileobj=archive) as tar:
            tar.extractall(dest, filter="data")
        return True

    return await asyncio.to_thread(_fetch)


async def remove(container):
    try:
        await asyncio.to_thread(container.remove, force=True)
    except docker.errors.NotFound:
        pass  # already removed, e.g. stopped by hand
