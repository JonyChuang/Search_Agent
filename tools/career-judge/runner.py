"""Local Python and SQL sandbox for the subset of the Judge0 API used by Search Agent."""
import base64
import binascii
import hmac
import json
import os
import re
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

OUTPUT_LIMIT = 65536
QUEUE_LIMIT = 20
RESULT_TTL = 600
SANDBOX_IMAGE = "python@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff"
BOOTSTRAP = """
import base64, io, json, os, resource, signal, sys
payload = json.load(sys.stdin)
source = base64.b64decode(payload['source']).decode('utf-8')
sys.stdin = io.TextIOWrapper(io.BytesIO(base64.b64decode(payload['stdin'])), encoding='utf-8')
resource.setrlimit(resource.RLIMIT_CPU, (2, 3))
resource.setrlimit(resource.RLIMIT_FSIZE, (131072, 131072))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
signal.signal(signal.SIGXCPU, lambda *_: os._exit(124))
signal.signal(signal.SIGALRM, lambda *_: os._exit(124))
signal.alarm(5)
try:
    candidate = compile(source, '<candidate>', 'exec')
except SyntaxError:
    sys.exit(66)
exec(candidate, {'__name__': '__main__'})
"""


def cleanup(docker, name):
    try:
        subprocess.run([docker, "rm", "-f", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        pass


def evaluate(docker, image, token, payload, expected):
    name = "search-agent-judge-" + token
    command = [docker, "run", "--rm", "--pull=never", "--name", name, "--network=none", "--read-only",
               "--log-driver=none", "--tmpfs=/tmp:noexec,nosuid,nodev,size=4m", "--user=65534:65534",
               "--cap-drop=ALL", "--security-opt=no-new-privileges", "--memory=64m", "--memory-swap=64m",
               "--pids-limit=16", "--cpus=1", "-i", "--entrypoint=python", image, "-I", "-B", "-c", BOOTSTRAP]
    deadline = time.monotonic() + 11
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        return 13
    output = bytearray()

    def feed_input():
        try:
            with process.stdin as stream:
                stream.write(payload)
        except OSError:
            pass

    def collect_output():
        with process.stdout as stream:
            output.extend(stream.read(OUTPUT_LIMIT + 1))

    writer = threading.Thread(target=feed_input, daemon=True)
    reader = threading.Thread(target=collect_output, daemon=True)
    writer.start()
    reader.start()
    while process.poll() is None and len(output) <= OUTPUT_LIMIT and time.monotonic() < deadline:
        time.sleep(0.025)
    if process.poll() is None:
        cleanup(docker, name)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)
        return 4 if len(output) > OUTPUT_LIMIT else 5
    reader.join(timeout=1)
    if reader.is_alive():
        return 13
    if len(output) > OUTPUT_LIMIT:
        return 4
    if process.returncode == 0:
        return 3 if bytes(output).strip() == expected.strip() else 4
    if process.returncode in (124, 142, 152):
        return 5
    if process.returncode == 66:
        return 6
    if process.returncode in (125, 126, 127):
        return 13
    return 11


class JudgeServer(ThreadingHTTPServer):
    def __init__(self, port, key, docker, image):
        super().__init__(("127.0.0.1", port), JudgeHandler)
        self.key, self.docker, self.image = key, docker, image
        self.lock = threading.Lock()
        self.results = {}
        self.pool = ThreadPoolExecutor(max_workers=2)

    def enqueue(self, payload, expected):
        with self.lock:
            now = time.monotonic()
            self.results = {key: value for key, value in self.results.items() if now - value[0] < RESULT_TTL}
            if sum(not future.done() for _, future in self.results.values()) >= QUEUE_LIMIT:
                return None
            token = str(uuid.uuid4())
            future = self.pool.submit(evaluate, self.docker, self.image, token, payload, expected)
            self.results[token] = (now, future)
            return token

    def status(self, token):
        with self.lock:
            saved = self.results.get(token)
        if not saved or time.monotonic() - saved[0] >= RESULT_TTL:
            return None
        future = saved[1]
        if not future.done():
            return 2 if future.running() else 1
        try:
            return future.result()
        except (OSError, subprocess.TimeoutExpired):
            return 13


class JudgeHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(5)
        super().setup()

    def log_message(self, *_args):
        pass

    def reply(self, status, value):
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if hmac.compare_digest(self.headers.get("X-Auth-Token", "").encode(), self.server.key):
            return True
        self.reply(401, {"error": "Unauthorized"})
        return False

    def do_GET(self):  # noqa: N802
        if not self.authorized():
            return
        path = urlsplit(self.path).path
        if path == "/config_info":
            self.reply(200, {"enable_network": False, "allow_enable_network": False})
            return
        found = re.fullmatch(r"/submissions/([a-f0-9-]{36})", path)
        status = self.server.status(found[1]) if found else None
        if status:
            self.reply(200, {"status": {"id": status}})
        else:
            self.reply(404, {"error": "Not found"})

    def do_POST(self):  # noqa: N802
        if not self.authorized():
            return
        if urlsplit(self.path).path != "/submissions":
            self.reply(404, {"error": "Not found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 200_000 or self.headers.get("Transfer-Encoding"):
                raise ValueError()
            body = json.loads(self.rfile.read(size))
            if body["language_id"] != 71 or body.get("enable_network") is not False:
                raise ValueError()
            code = base64.b64decode(body["source_code"], validate=True)
            stdin = base64.b64decode(body["stdin"], validate=True)
            expected = base64.b64decode(body["expected_output"], validate=True)
            if not code or len(code) > 96_000 or len(stdin) > OUTPUT_LIMIT or len(expected) > OUTPUT_LIMIT:
                raise ValueError()
            code.decode("utf-8")
            payload = json.dumps({"source": body["source_code"], "stdin": body["stdin"]}).encode("utf-8")
        except (ValueError, TimeoutError, KeyError, TypeError, binascii.Error):
            self.reply(400, {"error": "Invalid submission"})
            return
        token = self.server.enqueue(payload, expected)
        if token:
            self.reply(201, {"token": token})
        else:
            self.reply(429, {"error": "Sandbox queue is full"})


def main():
    key = os.environ.get("CAREER_JUDGE0_TOKEN", "").encode()
    if len(key) < 24:
        raise SystemExit("配置至少 24 字节的 CAREER_JUDGE0_TOKEN。")
    docker = os.environ.get("CAREER_JUDGE_DOCKER", "docker")
    if subprocess.run([docker, "image", "inspect", SANDBOX_IMAGE], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, timeout=8, check=False).returncode:
        raise SystemExit(f"请预先拉取隔离执行镜像 {SANDBOX_IMAGE}")
    with JudgeServer(int(os.environ.get("CAREER_JUDGE_PORT", "2358")), key, docker, SANDBOX_IMAGE) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
