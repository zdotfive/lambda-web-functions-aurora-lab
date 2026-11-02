"""Recycles the execution environments of the Event Functions so their DB connections close.

Idle Event Function environments keep their pg.Client (and, through RDS Proxy, the proxy's
connections) open after a run. Without a reset the next variant starts with the database
already near max_connections. Changing an environment variable makes Lambda replace every
environment. Run from the laptop (the loadgen has no Lambda permissions).

Usage: python scripts/reset_envs.py
"""

import time

import boto3

FUNCTIONS = ["lwf-event-direct", "lwf-event-proxy"]


def main():
    client = boto3.client("lambda", region_name="eu-west-1")
    stamp = str(int(time.time()))
    for fn in FUNCTIONS:
        env = client.get_function_configuration(FunctionName=fn)["Environment"]["Variables"]
        env["LAB_RESET"] = stamp
        client.update_function_configuration(FunctionName=fn, Environment={"Variables": env})
    for fn in FUNCTIONS:
        client.get_waiter("function_updated_v2").wait(FunctionName=fn)
        print(f"{fn}: environments recycled (LAB_RESET={stamp})")


if __name__ == "__main__":
    main()
