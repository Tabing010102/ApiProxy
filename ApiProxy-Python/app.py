import argparse
import json
import logging
import threading
from itertools import cycle
from urllib.parse import urlparse

import opencc
import requests
from flask import Flask, request
from requests.adapters import HTTPAdapter

parser = argparse.ArgumentParser()
parser.add_argument('-l', '--listen_host', default='127.0.0.1', help='Host to listen on')
parser.add_argument('-p', '--listen_port', default=8081, type=int, help='Port to listen on')
parser.add_argument('-c', '--config', default='config.json', help='Config file')
parser.add_argument('-d', '--debug', action='store_true', help='Enable debug mode')
args = parser.parse_args()

if args.debug:
    logging.basicConfig(level=logging.DEBUG)

with open(args.config, 'r') as f:
    config = json.load(f)


def get_requests_session(prefix: str, max_concurrency: int) -> requests.Session:
    session = requests.Session()
    if max_concurrency >= 1:
        adapter = HTTPAdapter(pool_connections=max_concurrency, pool_maxsize=max_concurrency)
        session.mount(prefix, adapter)
    return session


endpoints = [{'endpoint': c['endpoint'],
              'semaphore': threading.Semaphore(c['max_concurrency']),
              'timeout': c['timeout'],
              'session': get_requests_session(urlparse(c['endpoint']).scheme + '://', c['max_concurrency'])}
             for c in config['endpoints']]
endpoints_cycle = cycle(endpoints)

opencc_enabled = bool(config['enable_opencc'])
opencc_converter: opencc.OpenCC
if opencc_enabled:
    opencc_converter = opencc.OpenCC(config['opencc_config'])

app = Flask(__name__)


def get_next_available_endpoint():
    for endpoint in endpoints_cycle:
        if endpoint['semaphore'].acquire(blocking=False):
            return endpoint
    return None


def forward_request(request, endpoint):
    try:
        r = endpoint['session'].request(
            method=request.method,
            url=endpoint['endpoint'] + request.path,
            headers={key: value for (key, value) in request.headers if key != 'Host'},
            data=request.get_data(),
            cookies=request.cookies,
            timeout=endpoint['timeout'],
            allow_redirects=False)
        encoding = r.encoding if r.encoding else 'utf-8'
        app.logger.debug(f'Received response: {r.content.decode(encoding)}')

        if opencc_enabled:
            if opencc_enabled:
                json_ensure_ascii = False if (encoding == 'utf-8' or encoding == 'utf8') else True
                response_text = r.content.decode(encoding)
                response_json = json.loads(response_text)

                # chat completion api
                for choice in response_json.get('choices', []):
                    if 'message' in choice and 'content' in choice['message']:
                        choice['message']['content'] = opencc_converter.convert(choice['message']['content'])
                # completion api
                if 'content' in response_json:
                    response_json['content'] = opencc_converter.convert(response_json['content'])

                response_text = json.dumps(response_json, ensure_ascii=json_ensure_ascii, separators=(',', ':'))
                response_content = response_text.encode(encoding)
                app.logger.debug(f'Converted response: {response_text}')
                return response_content, r.status_code, r.raw.headers.items()
        else:
            return r.content, r.status_code, r.raw.headers.items()
    except Exception as e:
        return str(e), 500


@app.route('/', defaults={'path': ''}, methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'])
def catch_all(path):
    endpoint = get_next_available_endpoint()
    try:
        if endpoint:
            return forward_request(request, endpoint)
        else:
            return 'No available server', 503
    finally:
        if endpoint:
            endpoint['semaphore'].release()


if __name__ == '__main__':
    app.run(host=args.listen_host, port=args.listen_port)
