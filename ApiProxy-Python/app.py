import argparse
import json
import threading
from itertools import cycle

import requests
from flask import Flask, request

parser = argparse.ArgumentParser()
parser.add_argument('-l', '--listen_host', default='127.0.0.1', help='Host to listen on')
parser.add_argument('-p', '--listen_port', default=8081, type=int, help='Port to listen on')
parser.add_argument('-c', '--config', default='config.json', help='Config file')
args = parser.parse_args()

with open(args.config, 'r') as f:
    config = json.load(f)

endpoints = [{'endpoint': c['endpoint'],
              'semaphore': threading.Semaphore(c['max_concurrency']),
              'timeout': c['timeout']}
             for c in config]
endpoints_cycle = cycle(endpoints)

app = Flask(__name__)


def get_next_available_endpoint():
    for endpoint in endpoints_cycle:
        if endpoint['semaphore'].acquire(blocking=False):
            return endpoint
    return None


def forward_request(request, endpoint):
    try:
        r = requests.request(
            method=request.method,
            url=endpoint['endpoint'] + request.path,
            headers={key: value for (key, value) in request.headers if key != 'Host'},
            data=request.get_data(),
            cookies=request.cookies,
            timeout=endpoint['timeout'],
            allow_redirects=False)

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
