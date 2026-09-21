-- Zoho governor: settle one admission.
--
-- `sent = 1` converts the reservation into spend (Zoho counts attempts, so a
-- 429 or a 500 still costs a call). `sent = 0` gives the reservation back —
-- the request never left the client (circuit open, serialisation error, …).
--
-- Idempotent by lease id: the lease is removed from the in-flight set first and
-- the counters are only touched when that removal actually removed something,
-- so a retried release (redis-py retries on timeout) cannot double-count.
--
-- KEYS[1] day hash   zoho:gov:{pool}:day:{yyyymmdd}
-- KEYS[2] lease zset zoho:gov:{org}:inflight
--
-- ARGV: 1 lease_id, 2 cost, 3 sent(0/1), 4 background(0/1), 5 priority_rank,
--       6 day_ttl_s, 7 soft, 8 essential, 9 hard, 10 daily_limit
--
-- Returns {used, reserved, state}

local lease_id   = ARGV[1]
local cost       = tonumber(ARGV[2])
local sent       = tonumber(ARGV[3])
local background = tonumber(ARGV[4])
local rank       = ARGV[5]
local day_ttl    = tonumber(ARGV[6])
local soft       = tonumber(ARGV[7])
local essential  = tonumber(ARGV[8])
local hard       = tonumber(ARGV[9])
local daily      = tonumber(ARGV[10])

local removed = redis.call('ZREM', KEYS[2], lease_id)
if removed == 1 then
  redis.call('HINCRBY', KEYS[1], 'reserved', -cost)
  if sent == 1 then
    redis.call('HINCRBY', KEYS[1], 'used', cost)
    redis.call('HINCRBY', KEYS[1], 'p' .. rank, cost)
    if background == 1 then
      redis.call('HINCRBY', KEYS[1], 'used_bg', cost)
    end
  end
  redis.call('EXPIRE', KEYS[1], day_ttl)
end

local day = redis.call('HMGET', KEYS[1], 'used', 'reserved', 'exhausted')
local used      = tonumber(day[1]) or 0
local reserved  = tonumber(day[2]) or 0
local exhausted = tonumber(day[3]) or 0
if reserved < 0 then
  redis.call('HSET', KEYS[1], 'reserved', 0)
  reserved = 0
end
local committed = used + reserved

local state
if exhausted == 1 or committed >= daily then
  state = 'exhausted'
elseif committed >= hard then
  state = 'reserved_only'
elseif committed >= essential then
  state = 'essential'
elseif committed >= soft then
  state = 'conserve'
else
  state = 'open'
end
redis.call('HSET', KEYS[1], 'state', state)

return {used, reserved, state}
