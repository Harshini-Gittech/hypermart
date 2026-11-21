import os
import ssl
import json
from kafka import KafkaProducer, KafkaConsumer
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

def _ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

def create_producer():
    return KafkaProducer(
        bootstrap_servers=[os.getenv("KAFKA_BROKER")],
        security_protocol="SASL_SSL",
        sasl_mechanism="PLAIN",
        sasl_plain_username=os.getenv("KAFKA_USERNAME"),
        sasl_plain_password=os.getenv("KAFKA_PASSWORD"),
        ssl_context=_ssl_context(),
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        retries=5
    )

def create_consumer(topic="order_placed"):
    return KafkaConsumer(
        topic,
        bootstrap_servers=[os.getenv("KAFKA_BROKER")],
        group_id="search-sync-group",
        auto_offset_reset="latest",
        security_protocol="SASL_SSL",
        sasl_mechanism="PLAIN",
        sasl_plain_username=os.getenv("KAFKA_USERNAME"),
        sasl_plain_password=os.getenv("KAFKA_PASSWORD"),
        ssl_context=_ssl_context(),
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        session_timeout_ms=30000,
        heartbeat_interval_ms=3000
    )