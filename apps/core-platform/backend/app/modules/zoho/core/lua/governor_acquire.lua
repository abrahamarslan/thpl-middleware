-- Zoho governor: one atomic admission decision per outbound call.
--
-- Checks, in this order (cheapest refusal first, nothing is spent on a refusal):
--   1. governor state vs the caller's priority   (day ceiling thresholds)
--   2. daily ceiling for that priority           (hard stop at the contract limit)
--   3. pacing curve                              (background priorities only)
--   4. per-minute token bucket                   (Zoho: 100/min/org — code 44 blocks the ORG)
--   5. org-wide concurrency leases               (Zoho: ~10 concurrent — code 1070)
-- and only then reserves: day.reserved += cost, bucket -= cost, lease added.
--
-- The reservation is converted to `used` by governor_release.lua when the
-- request was actually sent, or given back when it never left the client.
--
-- KEYS[1] day hash   zoho:gov:{pool}:day:{yyyymmdd}
-- KEYS[2] rate hash  zoho:gov:{org}:minute
-- KEYS[3] lease zset zoho:gov:{org}:inflight
--
-- ARGV
--   1 now_ms            8 hard_threshold      15 background(0/1)
--   2 priority_rank     9 reserve_calls       16 allowance (background ceiling now)
--   3 cost             10 rate_capacity       17 day_ttl_s
--   4 lease_id         11 rate_refill_per_ms  18 rate_reserve (tokens this priority may not take)
--   5 lease_ttl_ms     12 concurrency_limit
--   6 soft_threshold   13 daily_hard_limit
--   7 essential_threshold 14 lease_ttl_ms (unused placeholder kept for clarity)
--
-- Returns {1, state, tokens_left, used, reserved}
--      or {0, reason, retry_after_ms, state, used}

local now_ms        = tonumber(ARGV[1])
local rank          = tonumber(ARGV[2])
local cost          = tonumber(ARGV[3])
local lease_id      = ARGV[4]
local lease_ttl_ms  = tonumber(ARGV[5])
local soft          = tonumber(ARGV[6])
local essential     = tonumber(ARGV[7])
local hard          = tonumber(ARGV[8])
local reserve_calls = tonumber(ARGV[9])
local capacity      = tonumber(ARGV[10])
local refill_per_ms = tonumber(ARGV[11])
local conc_limit    = tonumber(ARGV[12])
local daily_limit   = tonumber(ARGV[13])
local background    = tonumber(ARGV[15])
local allowance     = tonumber(ARGV[16])
local day_ttl       = tonumber(ARGV[17])
local rate_reserve  = tonumber(ARGV[18])

-- ── 1. day counters & state ────────────────────────────────────────────────
local day = redis.call('HMGET', KEYS[1], 'used', 'reserved', 'used_bg', 'exhausted')
local used      = tonumber(day[1]) or 0
local reserved  = tonumber(day[2]) or 0
local used_bg   = tonumber(day[3]) or 0
local exhausted = tonumber(day[4]) or 0
local committed = used + reserved

local state
if exhausted == 1 or committed >= daily_limit then
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

-- priority ranks: 0 interactive, 1 push, 2 refresh, 3 incremental, 4 reconcile
local max_rank_for_state = { open = 4, conserve = 3, essential = 2, reserved_only = 0, exhausted = -1 }
if rank > max_rank_for_state[state] then
  return {0, 'state', 0, state, used}
end

-- ── 2. daily ceiling for this priority ─────────────────────────────────────
-- Interactive (and commands flagged critical, which callers send as rank 0)
-- may dip into the reserve above the hard threshold, never past the limit.
local ceiling = hard
if rank == 0 then
  local with_reserve = hard + reserve_calls
  ceiling = (with_reserve < daily_limit) and with_reserve or daily_limit
end
if committed + cost > ceiling then
  return {0, 'quota', 0, state, used}
end

-- ── 3. pacing (background only) ────────────────────────────────────────────
if background == 1 and (used_bg + cost) > allowance then
  return {0, 'pacing', 60000, state, used}
end

-- ── 4. per-minute token bucket ─────────────────────────────────────────────
local bucket = redis.call('HMGET', KEYS[2], 'tokens', 'ts')
local tokens = tonumber(bucket[1])
local ts     = tonumber(bucket[2])
if tokens == nil then tokens = capacity end
if ts == nil then ts = now_ms end
local elapsed = now_ms - ts
if elapsed < 0 then elapsed = 0 end
tokens = tokens + elapsed * refill_per_ms
if tokens > capacity then tokens = capacity end

if (tokens - cost) < rate_reserve then
  local needed = (rate_reserve + cost) - tokens
  local wait_ms = 1000
  if refill_per_ms > 0 then wait_ms = math.ceil(needed / refill_per_ms) end
  -- persist the refill so concurrent callers see the same clock
  redis.call('HSET', KEYS[2], 'tokens', tokens, 'ts', now_ms)
  redis.call('PEXPIRE', KEYS[2], 120000)
  return {0, 'rate', wait_ms, state, used}
end

-- ── 5. org-wide concurrency ────────────────────────────────────────────────
redis.call('ZREMRANGEBYSCORE', KEYS[3], '-inf', now_ms)
if redis.call('ZCARD', KEYS[3]) >= conc_limit then
  return {0, 'concurrency', 250, state, used}
end

-- ── 6. admit ───────────────────────────────────────────────────────────────
tokens = tokens - cost
redis.call('HSET', KEYS[2], 'tokens', tokens, 'ts', now_ms)
redis.call('PEXPIRE', KEYS[2], 120000)
redis.call('ZADD', KEYS[3], now_ms + lease_ttl_ms, lease_id)
redis.call('PEXPIRE', KEYS[3], 300000)
redis.call('HINCRBY', KEYS[1], 'reserved', cost)
redis.call('HSET', KEYS[1], 'state', state)
redis.call('EXPIRE', KEYS[1], day_ttl)

return {1, state, tostring(tokens), used, reserved + cost}
