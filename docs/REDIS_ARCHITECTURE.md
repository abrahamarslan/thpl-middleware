# Enterprise Redis Architecture

This document outlines the design and resilience patterns of the Redis integration in `th-middleware`. 

## 1. Unified Connection Pool
We use a single `redis_client` initialized in `app/database/redis.py` for both the FastAPI web server and the Celery background workers. 
This is a strict architectural requirement (see `master-prompt.md`) to prevent connection pool fragmentation. We **do not** use FastAPI-specific DI libraries (like `fastapi-redis-sdk`) to manage the connection lifecycle, as Celery workers do not run FastAPI lifespans and would be cut off from the token manager and rate limiters.

## 2. Enterprise Resilience
The `redis_client` is configured with strict safeguards to survive transient network partitions without hanging the application:
- **`socket_timeout` (5.0s)**: Prevents the client from waiting indefinitely on read/write if the network drops.
- **`socket_connect_timeout` (2.0s)**: Fails fast if the Redis host is unreachable during connection establishment.
- **`health_check_interval` (30s)**: Actively probes idle connections in the pool and evicts dead ones before they are handed to the application.
- **`retry` & `retry_on_timeout`**: Uses `ExponentialBackoff` with up to 3 retries. If a command times out due to a millisecond network blip, the client will transparently retry it without throwing an exception to the caller.

## 3. Dependency Injection (FastAPI)
While Celery and core singleton services (like the Circuit Breaker) import the global `redis_client` directly, FastAPI API routes should use the provided Dependency Injection factory:
```python
from fastapi import Depends
from app.database.redis import get_redis

@router.get("/example")
async def example_route(redis = Depends(get_redis)):
    ...
```
This enables seamless mocking during unit tests via `app.dependency_overrides[get_redis] = mock_redis`.

## 4. Pipelining
For multi-key operations (like storing both an Access Token and a Refresh Token), we mandate the use of `redis.pipeline()`:
```python
async with redis_client.pipeline(transaction=True) as pipe:
    pipe.set("key1", "val1")
    pipe.set("key2", "val2")
    await pipe.execute()
```
This groups the commands into a single TCP packet, halving the network latency compared to sequential `await` calls.

## 5. Graceful Degradation
For non-critical data paths (like fast-path API caching in `zoho/service.py`), cache operations are wrapped in a `try...except redis.exceptions.ConnectionError` block. If Redis is down, the application logs a warning and smoothly falls back to the primary database or upstream API. We never return a `500 Internal Server Error` solely due to an optional cache miss.
