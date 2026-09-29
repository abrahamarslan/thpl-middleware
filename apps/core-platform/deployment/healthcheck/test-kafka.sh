#!/usr/bin/env bash
# ==============================================================================
# Kafka Healthcheck (KRaft mode, apache/kafka image)
# ==============================================================================
set -euo pipefail
source "$(dirname "$0")/_common.sh"

KAFKA_BIN="/opt/kafka/bin"

# Every kafka-* tool is a full JVM and kafka-run-class.sh inherits the broker's
# KAFKA_HEAP_OPTS=-Xmx1G. Without clamping, each probe spawns a second 1G-heap
# JVM inside the same cgroup (OOM risk) and takes ages to start on this VM.
# Same reasoning as the compose healthcheck — see docker-compose.yml.
HEAP="-Xmx128m -Xms64m"

kafka_exec() {
    local script="$1"; shift
    docker exec -e KAFKA_HEAP_OPTS="$HEAP" kafka "$KAFKA_BIN/$script" "$@"
}

kafka_exec_stdin() {
    local script="$1"; shift
    docker exec -i -e KAFKA_HEAP_OPTS="$HEAP" kafka "$KAFKA_BIN/$script" "$@"
}

kafka_exec_timeout() {
    local seconds="$1"; shift
    local script="$1"; shift
    docker exec -e KAFKA_HEAP_OPTS="$HEAP" kafka timeout "$seconds" "$KAFKA_BIN/$script" "$@"
}

topic_crud() {
    local rc
    kafka_exec kafka-topics.sh --bootstrap-server localhost:9092 \
        --create --topic _healthcheck_test --partitions 1 --replication-factor 1 \
        --if-not-exists >/dev/null 2>&1
    kafka_exec kafka-topics.sh --bootstrap-server localhost:9092 \
        --list 2>/dev/null | grep -q "_healthcheck_test"
    rc=$?
    kafka_exec kafka-topics.sh --bootstrap-server localhost:9092 \
        --delete --topic _healthcheck_test >/dev/null 2>&1 || true
    return $rc
}

roundtrip() {
    local topic="_healthcheck_roundtrip"
    local msg="healthcheck-$(date +%s)"
    local received

    kafka_exec kafka-topics.sh --bootstrap-server localhost:9092 \
        --create --topic "$topic" --partitions 1 --replication-factor 1 \
        --if-not-exists >/dev/null 2>&1

    echo "$msg" | kafka_exec_stdin kafka-console-producer.sh \
        --bootstrap-server localhost:9092 --topic "$topic" >/dev/null 2>&1

    # The consumer JVM needs ~10s just to join and fetch on this VM; 5s (the old
    # value) guaranteed a false failure. 30s is the ceiling, not the norm.
    received=$(kafka_exec_timeout 30 kafka-console-consumer.sh \
        --bootstrap-server localhost:9092 --topic "$topic" \
        --from-beginning --max-messages 1 2>/dev/null || true)

    kafka_exec kafka-topics.sh --bootstrap-server localhost:9092 \
        --delete --topic "$topic" >/dev/null 2>&1 || true

    echo "$received" | grep -q "$msg"
}

section "Kafka (KRaft)"

# 1. Container running
check "Container running" container_running kafka

# 2. Broker API version check
check "Broker API reachable" \
    kafka_exec kafka-broker-api-versions.sh --bootstrap-server localhost:9092

# 3. Topic CRUD test
check "Topic create/list/delete" topic_crud

# 4. Produce and consume a test message
check "Produce/consume round-trip" roundtrip

# 5. Kafbat UI
check "Kafbat UI running" container_running kafbat-ui

summary
