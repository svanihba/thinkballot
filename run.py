"""Run ThinkBallot: python run.py [--port 8000]"""

import argparse

from werkzeug.serving import run_simple

from thinkballot.app import create_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    # threaded: the web service calls the other services in this same process over HTTP
    run_simple(args.host, args.port, create_app(), threaded=True)
