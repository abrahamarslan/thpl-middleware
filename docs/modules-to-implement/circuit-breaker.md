The count-based sliding window (using a simple Redis List) was a step in the right direction, but in a true high-throughput enterprise environment, it introduces a subtle flaw: **Time Decay**. If your system processes 100 requests, and then traffic stops for three days, a list-based window still remembers those 3-day-old failures because the list only flushes when new requests push the old ones out.

The enterprise standard for this is a **Time-Based Sliding Window using Redis Sorted Sets (`ZSET`)**. By using timestamps as the score, Redis can automatically purge stale metrics, ensuring the circuit breaker's math is strictly based on the actual time window (e.g., the last 60 seconds), regardless of traffic volume.

Here is the complete, production-ready implementation, culminating in an end-to-end FastAPI simulation route you can run to watch it work.

---

### 1. The Configuration (`app/core/conf.py`)

```python
class Settings(BaseSettings):
    # ... existing settings ...
    
    # Circuit Breaker Configuration (Time-Based)
    CB_WINDOW_DURATION: int = 60          # Time window in seconds (e.g., look at the last 60s)
    CB_MINIMUM_CALLS: int = 10            # Min calls required in the window before calculating rates
    CB_FAILURE_RATE_THRESHOLD: float = 0.5  # Trip if > 50% of calls fail
    CB_SLOW_CALL_RATE_THRESHOLD: float = 0.5 # Trip if > 50% of calls are slow
    CB_SLOW_CALL_DURATION: float = 5.0    # Seconds before a call is considered "slow"
    CB_OPEN_TIMEOUT: int = 30             # Seconds to wait in OPEN state before probing

```

---

### 2. The ZSET Circuit Breaker (`app/modules/zoho/core/circuit_breaker.py`)

This utilizes `ZREMRANGEBYSCORE` to natively purge metrics older than 60 seconds on every execution.

```python
import time
import uuid
from enum import Enum
from app.database.redis import redis_client
from app.core.conf import settings

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class DistributedCircuitBreaker:
    def __init__(self, service_name: str):
        self.service = service_name
        self.state_key = f"cb:{service_name}:state"
        self.window_key = f"cb:{service_name}:window"
        self.probe_lock_key = f"cb:{service_name}:probe_lock"

    async def get_state(self) -> CircuitState:
        state = await redis_client.get(self.state_key)
        if not state:
            return CircuitState.CLOSED
            
        state_str = state.decode('utf-8')
        
        if state_str == CircuitState.OPEN.value:
            # If the OPEN state key has expired (TTL), it transitions to HALF_OPEN
            ttl = await redis_client.ttl(self.state_key)
            if ttl <= 0:
                return CircuitState.HALF_OPEN
        
        return CircuitState(state_str)

    async def acquire_probe_lock(self) -> bool:
        """Atomic lock: Prevents the Thundering Herd during HALF_OPEN recovery."""
        acquired = await redis_client.set(self.probe_lock_key, "locked", nx=True, ex=15)
        return bool(acquired)

    async def record_result(self, is_success: bool, duration: float):
        state = await self.get_state()

        if state == CircuitState.HALF_OPEN:
            if is_success:
                await self._close_circuit()
            else:
                await self._open_circuit()
            return

        if state == CircuitState.CLOSED:
            # 0 = Success, 1 = Failure, 2 = Slow
            if not is_success:
                outcome = 1
            elif duration >= settings.CB_SLOW_CALL_DURATION:
                outcome = 2
            else:
                outcome = 0

            current_time = time.time()
            cutoff_time = current_time - settings.CB_WINDOW_DURATION
            
            # Unique member ID prevents Redis from overwriting simultaneous events
            member_value = f"{current_time}:{outcome}:{uuid.uuid4().hex[:8]}"

            # Atomic Pipeline: Purge old -> Add new -> Fetch window
            async with redis_client.pipeline() as pipe:
                # Remove metrics older than the window duration
                pipe.zremrangebyscore(self.window_key, "-inf", cutoff_time)
                # Add current metric using timestamp as the score
                pipe.zadd(self.window_key, {member_value: current_time})
                # Fetch remaining relevant metrics
                pipe.zrange(self.window_key, 0, -1)
                # Keep key alive slightly longer than the window to prevent memory leaks
                pipe.expire(self.window_key, settings.CB_WINDOW_DURATION * 2)
                
                results = await pipe.execute()
            
            # The 3rd command in the pipeline (zrange) returns the active window data
            active_window = results[2]
            await self._evaluate_metrics(active_window)

    async def _evaluate_metrics(self, active_window: list):
        total_calls = len(active_window)

        if total_calls < settings.CB_MINIMUM_CALLS:
            return

        failures = 0
        slow_calls = 0

        for member_bytes in active_window:
            # Format: timestamp:outcome:uuid
            outcome = int(member_bytes.decode('utf-8').split(":")[1])
            if outcome == 1: failures += 1
            if outcome == 2: slow_calls += 1

        if (failures / total_calls >= settings.CB_FAILURE_RATE_THRESHOLD or 
            slow_calls / total_calls >= settings.CB_SLOW_CALL_RATE_THRESHOLD):
            await self._open_circuit()

    async def _open_circuit(self):
        """Trips the circuit, enforcing the 30-second blackout period."""
        await redis_client.setex(
            self.state_key, 
            settings.CB_OPEN_TIMEOUT, 
            CircuitState.OPEN.value
        )
        await redis_client.delete(self.window_key)

    async def _close_circuit(self):
        """Fully recovers the circuit."""
        await redis_client.delete(self.state_key)
        await redis_client.delete(self.window_key)
        await redis_client.delete(self.probe_lock_key)

```

---

### 3. The Client Integration (`app/modules/zoho/core/client.py`)

```python
import time
from httpx import AsyncClient, HTTPError
from app.modules.zoho.core.circuit_breaker import DistributedCircuitBreaker, CircuitState
from app.modules.zoho.core.exceptions import ZohoCircuitOpenError

class ZohoClient:
    def __init__(self):
        self.breaker = DistributedCircuitBreaker("zoho_api")
        self.http_client = AsyncClient()

    async def request(self, method: str, url: str, **kwargs):
        state = await self.breaker.get_state()

        if state == CircuitState.OPEN:
            raise ZohoCircuitOpenError("Circuit is OPEN. Fast-failing request.")

        if state == CircuitState.HALF_OPEN:
            if not await self.breaker.acquire_probe_lock():
                raise ZohoCircuitOpenError("Circuit is HALF_OPEN. Another worker is probing.")

        start_time = time.time()
        is_success = False

        try:
            # Simulated upstream call
            response = await self.http_client.request(method, url, **kwargs)
            response.raise_for_status()
            is_success = True
            return response.json()
            
        except HTTPError as exc:
            # 5xx errors and timeouts trigger the circuit. 4xx (Bad Request) do not.
            if hasattr(exc, 'response') and exc.response and exc.response.status_code >= 500:
                is_success = False
            else:
                is_success = True 
            raise

        finally:
            duration = time.time() - start_time
            await self.breaker.record_result(is_success, duration)

zoho_client = ZohoClient()

```

---

### 4. End-to-End Simulation Route (`app/modules/zoho/api.py`)

Add this endpoint to watch the entire distributed system evaluate, trip, and recover in real-time. It intercepts the HTTP call and simulates specific latency or HTTP statuses.

```python
import asyncio
from fastapi import APIRouter, Query
from app.modules.zoho.core.client import zoho_client
from app.modules.zoho.core.exceptions import ZohoCircuitOpenError

router = APIRouter(prefix="/simulate", tags=["Circuit Simulation"])

@router.get("/zoho")
async def simulate_zoho_call(
    http_status: int = Query(200, description="Force a specific HTTP response"),
    delay: float = Query(0.0, description="Force request latency (seconds)")
):
    """
    Hit this endpoint 10+ times with http_status=500 to trip the circuit.
    Hit it once with delay=6.0 ten times to trip the slow-call circuit.
    """
    # 1. Check current state for the response payload
    initial_state = await zoho_client.breaker.get_state()
    
    try:
        # Mocking the httpx request dynamically for the simulation
        async def mock_request(*args, **kwargs):
            await asyncio.sleep(delay)
            from httpx import Response, Request, HTTPStatusError
            mock_resp = Response(http_status, json={"status": "ok"})
            if http_status >= 400:
                raise HTTPStatusError("Mock Error", request=Request("GET", ""), response=mock_resp)
            return mock_resp
            
        zoho_client.http_client.request = mock_request
        
        # Execute
        result = await zoho_client.request("GET", "https://books.zoho.com/api/v3/contacts")
        
        return {
            "execution": "Success",
            "initial_state": initial_state.value,
            "final_state": (await zoho_client.breaker.get_state()).value
        }

    except ZohoCircuitOpenError as e:
        return {
            "execution": "Fast-Failed (Circuit Tripped)",
            "initial_state": initial_state.value,
            "message": str(e)
        }
        
    except Exception as e:
        return {
            "execution": f"Upstream Failure (HTTP {http_status})",
            "initial_state": initial_state.value,
            "final_state": (await zoho_client.breaker.get_state()).value
        }

```