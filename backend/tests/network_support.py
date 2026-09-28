"""Real loopback sockets for transport assertions; no external targets."""

import asyncio
import socket
from contextlib import asynccontextmanager

import uvicorn


@asynccontextmanager
async def serve(app):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    sock.setblocking(False)
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="critical",
            access_log=False,
            proxy_headers=False,
            lifespan="on",
        )
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError("Fixture startup failed")
                await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}", port
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, 10)
        except TimeoutError:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        sock.close()
