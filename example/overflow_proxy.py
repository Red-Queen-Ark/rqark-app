import json
import os
import re
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get('OVERFLOW_UPSTREAM', 'http://127.0.0.1:11434')
PORT = int(os.environ.get('OVERFLOW_PORT', '11500'))
MAX_TOKENS = int(os.environ.get('OVERFLOW_MAX_TOKENS', '4096'))
ERROR_MODE = os.environ.get('OVERFLOW_ERROR_MODE', 'openai')
CJK = re.compile(r'[\u3000-\u9fff\uff00-\uffef]')


def estimate_tokens(payload: bytes) -> int:
    text = payload.decode('utf-8', 'ignore')
    cjk = len(CJK.findall(text))
    return cjk + (len(payload) - cjk * 3) // 4


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(self, status: int, body: bytes, content_type: str = 'application/json'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _overflow(self, tokens: int):
        message = f'request ({tokens} tokens) exceeds the available context size ({MAX_TOKENS} tokens), try increasing it'
        if ERROR_MODE == 'native':
            inner = {'code': 400, 'message': message, 'type': 'exceed_context_size_error', 'n_prompt_tokens': tokens, 'n_ctx': MAX_TOKENS}
            body = {'error': json.dumps({'error': inner})}
        else:
            body = {'error': {'message': message, 'type': 'invalid_request_error', 'param': None, 'code': 'context_length_exceeded'}}
        self._send(400, json.dumps(body).encode())

    def do_POST(self):
        length = int(self.headers.get('Content-Length', '0'))
        payload = self.rfile.read(length)
        tokens = estimate_tokens(payload)
        if tokens > MAX_TOKENS:
            self._overflow(tokens)
            return
        request = urllib.request.Request(
            f'{UPSTREAM}{self.path}',
            data=payload,
            headers={k: v for k, v in self.headers.items() if k.lower() not in ('host', 'content-length')},
            method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=1800) as response:
                self._send(response.status, response.read(), response.headers.get('Content-Type', 'application/json'))
        except urllib.error.HTTPError as error:
            self._send(error.code, error.read(), error.headers.get('Content-Type', 'application/json'))
        except Exception as error:
            self._send(502, json.dumps({'error': {'message': str(error), 'type': 'proxy_error'}}).encode())


if __name__ == '__main__':
    print(f'overflow_proxy :{PORT} -> {UPSTREAM} | max_tokens={MAX_TOKENS} mode={ERROR_MODE}', file=sys.stderr)
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
