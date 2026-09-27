"""Platform smoke test (spec 01 §10.4): one Kafka round trip and one Postgres round trip.

Usage: uv run python scripts/smoke/smoke.py [.env.<env>]
Reads only environment contract keys. Exits non-zero on any failure.
"""
import sys
import uuid
from pathlib import Path

import psycopg
from confluent_kafka import Consumer, KafkaException, Producer, TopicPartition
from psycopg import sql


def load_env(path):
    env = {}
    for line in Path(path).read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key] = value
    return env


def kafka_round_trip(env):
    topic, marker = env["EVENTS_TOPIC"], f"smoke-{uuid.uuid4()}"
    delivered = {}

    def on_delivery(err, msg):
        if err:
            raise KafkaException(err)
        delivered["tp"] = TopicPartition(msg.topic(), msg.partition(), msg.offset())

    producer = Producer({"bootstrap.servers": env["KAFKA_BOOTSTRAP_SERVERS"], "acks": "all"})
    producer.produce(topic, key=marker, value=marker.encode(), headers={"smoke": "true"}, on_delivery=on_delivery)
    if producer.flush(15) != 0 or "tp" not in delivered:
        raise RuntimeError("message was not delivered")

    consumer = Consumer({
        "bootstrap.servers": env["KAFKA_BOOTSTRAP_SERVERS"],
        "group.id": marker,
        "enable.auto.commit": False,
    })
    try:
        consumer.assign([delivered["tp"]])
        msg = consumer.poll(15)
        if msg is None or msg.error() or msg.value() != marker.encode():
            raise RuntimeError(f"did not read back the message: {msg and (msg.error() or msg.value())}")
    finally:
        consumer.close()
    print(f"kafka    ok  {topic}[{delivered['tp'].partition}]@{delivered['tp'].offset}")


def postgres_round_trip(env):
    table = sql.Identifier(env["WAREHOUSE_RAW_SCHEMA"], f"smoke_{uuid.uuid4().hex[:12]}")
    with psycopg.connect(env["WAREHOUSE_DSN"], connect_timeout=10) as conn:
        try:
            conn.execute(sql.SQL("CREATE TABLE {} (v text)").format(table))
            conn.execute(sql.SQL("INSERT INTO {} VALUES ('smoke')").format(table))
            row = conn.execute(sql.SQL("SELECT v FROM {}").format(table)).fetchone()
            if row != ("smoke",):
                raise RuntimeError(f"unexpected row {row}")
        finally:
            conn.rollback()
            conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(table))
            conn.commit()
    print(f"postgres ok  {env['WAREHOUSE_RAW_SCHEMA']} as ingest_writer")


def main():
    env_file = sys.argv[1] if len(sys.argv) > 1 else ".env.local"
    if not Path(env_file).exists():
        sys.exit(f"smoke: {env_file} not found; run `make up` first")
    env = load_env(env_file)
    try:
        kafka_round_trip(env)
        postgres_round_trip(env)
    except Exception as exc:  # any failure fails the smoke test
        sys.exit(f"smoke: FAILED: {exc}")
    print("smoke: ok")


if __name__ == "__main__":
    main()
