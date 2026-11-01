# -*- coding: utf-8 -*-
"""Origin 내장 Python에서 도는 브리지 서버.

설계
- 스레드를 쓰지 않는다. LabTalk timer가 UI 스레드에서 pump()를 주기적으로 호출하고,
  pump()는 select(timeout=0)로 소켓을 확인해 쌓인 요청만 처리한 뒤 바로 돌아온다.
  -> originpro 호출이 항상 UI 스레드에서 일어나고, 내장 Python의 스레드 제약을 피한다.
- 127.0.0.1 에만 바인딩, 요청마다 토큰 검사.
- Python 3.8 문법만 사용.

테스트에서는 Bridge(dispatcher=가짜함수)로 Origin 없이 돌린다.
"""
import hmac
import os
import select
import socket
import sys

try:
    from . import ilhae_protocol as P
except ImportError:
    import ilhae_protocol as P

MAX_REQUESTS_PER_PUMP = 8


def token_path():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".origin-ilhae")
    return os.path.join(base, "origin-ilhae", "token")


def load_or_create_token(path=None):
    """토큰 파일을 읽거나 새로 만든다. %LOCALAPPDATA% 는 기본적으로 본인 계정만 접근 가능하다."""
    path = path or token_path()
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            tok = f.read().strip()
        if tok:
            return tok
    import secrets
    tok = secrets.token_urlsafe(32)
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "w", encoding="utf-8") as f:
        f.write(tok)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return tok


class Bridge(object):
    def __init__(self, token, dispatcher, host=P.DEFAULT_HOST, port=P.DEFAULT_PORT):
        self.token = token
        self.dispatcher = dispatcher
        self.host = host
        self.port = port
        self.server = None
        self.clients = {}  # socket -> 받은 바이트 버퍼
        self.handled = 0

    def start(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if sys.platform == "win32":
            # 다른 프로세스가 같은 포트를 가로채지 못하게 배타적으로 바인딩
            s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", -5), 1)
        s.bind((self.host, self.port))
        s.listen(4)
        s.setblocking(False)
        self.server = s
        self.port = s.getsockname()[1]
        return self.port

    def stop(self):
        for c in list(self.clients):
            self._drop(c)
        if self.server is not None:
            self.server.close()
            self.server = None

    def _drop(self, c):
        try:
            c.close()
        except Exception:
            pass
        self.clients.pop(c, None)

    def pump(self, timeout=0.0):
        """대기 중인 연결·요청을 처리하고 처리한 요청 수를 돌려준다."""
        if self.server is None:
            return 0
        socks = [self.server] + list(self.clients)
        try:
            readable, _, _ = select.select(socks, [], [], timeout)
        except (OSError, ValueError):
            return 0
        done = 0
        for s in readable:
            if s is self.server:
                try:
                    c, addr = self.server.accept()
                except OSError:
                    continue
                if addr[0] != "127.0.0.1":
                    c.close()
                    continue
                c.setblocking(False)
                self.clients[c] = b""
                continue
            try:
                chunk = s.recv(1 << 20)
            except OSError:
                self._drop(s)
                continue
            if not chunk:
                self._drop(s)
                continue
            buf = self.clients.get(s, b"") + chunk
            if len(buf) > P.MAX_LINE_BYTES:
                self._drop(s)
                continue
            while b"\n" in buf and done < MAX_REQUESTS_PER_PUMP:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    self._send(s, self.handle_line(line))
                    done += 1
            if s in self.clients:
                self.clients[s] = buf
        self.handled += done
        return done

    def handle_line(self, line):
        try:
            req = P.decode(line)
        except Exception:
            return {"id": None, "ok": False,
                    "error": P.error_payload("BAD_JSON", "요청 JSON을 해석할 수 없습니다.")}
        rid = req.get("id")
        if not hmac.compare_digest(str(req.get("token", "")), str(self.token)):
            return {"id": rid, "ok": False, "error": P.error_payload(
                "AUTH_FAILED", "브리지 토큰이 맞지 않습니다.", recoverable=False,
                next_actions=["Origin에서 브리지를 다시 시작하고 MCP 서버를 재시작하세요."])}
        resp = self.dispatcher(req.get("op"), req.get("args") or {})
        resp["id"] = rid
        return resp

    def _send(self, s, obj):
        data = P.encode(obj)
        s.setblocking(True)  # 응답은 한 번에 끝까지 보낸다
        try:
            s.sendall(data)
        except OSError:
            self._drop(s)
        finally:
            if s in self.clients:
                s.setblocking(False)


# ---------------------------------------------------------------- Origin 안에서 쓰는 진입점

_BRIDGE = None


def start(port=P.DEFAULT_PORT):
    """Origin 스크립트 창: run -pyf "...\\ilhae_start.py" 가 호출한다."""
    global _BRIDGE
    if _BRIDGE is not None:
        return _BRIDGE.port
    try:
        from . import ilhae_ops as ops
    except ImportError:
        import ilhae_ops as ops
    _BRIDGE = Bridge(load_or_create_token(), ops.dispatch, port=port)
    p = _BRIDGE.start()
    import originpro as op
    # UI 스레드에서 0.1초마다 pump() 호출 [PoC 필요: timer 주기·충돌]
    op.lt_exec('timer 0.1; def timer {run -py "import ilhae_bridge; ilhae_bridge.pump()";};')
    return p


def pump():
    if _BRIDGE is not None:
        _BRIDGE.pump(0.0)


def stop():
    global _BRIDGE
    try:
        import originpro as op
        op.lt_exec("timer -k;")
    except Exception:
        pass
    if _BRIDGE is not None:
        _BRIDGE.stop()
        _BRIDGE = None
