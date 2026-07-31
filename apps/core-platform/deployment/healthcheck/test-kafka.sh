#!/usr/bin/env bash
# ==============================================================================
# Kafka Healthcheck (KRaft mode, apache/kafka image)
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

KAFKA_BIN="/opt/kafka/bin"

section "Kafka (KRaft)"

# 1. Container running
check "Container running" container_running kafka

# 2. Broker API version check
check "Broker API reachable" \
    docker exec kafka "$KAFKA_BIN/kafka-broker-api-versions.sh" --bootstrap-server localhost:9092

# 3. Topic CRUD test
check "Topic create/list/delete" bash -c '
    docker exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 \
        --create --topic _healthcheck_test --partitions 1 --replication-factor 1 \
        --if-not-exists >/dev/null 2>&1

    docker exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 \
        --list 2>/dev/null | grep -q "_healthcheck_test"
    RESULT=$?

    docker exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 \
        --delete --topic _healthcheck_test >/dev/null 2>&1 || true

    exit $RESULT
'

# 4. Produce and consume a test message
check "Produce/consume round-trip" bash -c '
    TOPIC="_healthcheck_roundtrip"
    MSG="healthcheck-$(date +%s)"

    docker exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 \
        --create --topic "$TOPIC" --partitions 1 --replication-factor 1 \
        --if-not-exists >/dev/null 2>&1

    echo "$MSG" | docker exec -i kafka /opt/kafka/bin/kafka-console-producer.sh \
        --bootstrap-server localhost:9092 --topic "$TOPIC" >/dev/null 2>&1

    RECEIVED=$(docker exec kafka timeout 5 /opt/kafka/bin/kafka-console-consumer.sh \
        --bootstrap-server localhost:9092 --topic "$TOPIC" \
        --from-beginning --max-messages 1 2>/dev/null || echo "")

    docker exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 \
        --delete --topic "$TOPIC" >/dev/null 2>&1 || true

    echo "$RECEIVED" | grep -q "$MSG"
'

# 5. Kafbat UI
check "Kafbat UI running" container_running kafbat-ui

summary
