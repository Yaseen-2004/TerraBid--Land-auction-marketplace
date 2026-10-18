--[[
  Atomic auction status transition. ENDED and CANCELLED are terminal: once Redis
  has closed an auction no later transition can reopen it, and because bid.lua
  checks the status inside the same single-threaded engine, no bid can be
  accepted after the close is applied.

  KEYS[1]  auction state hash
  ARGV[1]  target status
  ARGV[2]  start_ms ('' keeps current)
  ARGV[3]  end_ms   ('' keeps current)
]]

if redis.call('EXISTS', KEYS[1]) == 0 then
  return cjson.encode({code = 'NOT_LOADED'})
end

local target = ARGV[1]
local current = redis.call('HGET', KEYS[1], 'auction_status') or ''

if (current == 'ENDED' or current == 'CANCELLED') and current ~= target then
  return cjson.encode({code = 'TERMINAL', auction_status = current})
end

if ARGV[2] ~= '' then
  redis.call('HSET', KEYS[1], 'start_ms', ARGV[2])
end
if ARGV[3] ~= '' then
  redis.call('HSET', KEYS[1], 'end_ms', ARGV[3])
end
redis.call('HSET', KEYS[1], 'auction_status', target)
redis.call('HINCRBY', KEYS[1], 'version', 1)

local flat = redis.call('HGETALL', KEYS[1])
local state = {}
for i = 1, #flat, 2 do
  state[flat[i]] = flat[i + 1]
end

return cjson.encode({code = 'OK', changed = (current ~= target), previous_status = current, state = state})
