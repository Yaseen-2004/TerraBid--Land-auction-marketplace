--[[
  Load auction state from PostgreSQL into Redis, but only if Redis has no state yet.
  Never overwrites live state, so concurrent hydrations (e.g. after a Redis restart)
  cannot clobber bids accepted in the meantime.

  KEYS[1]  auction state hash
  ARGV[1]  TTL in seconds ('0' for no expiry)
  ARGV[2..] field/value pairs
]]

if redis.call('EXISTS', KEYS[1]) == 1 then
  return 0
end

local fields = {}
for i = 2, #ARGV do
  fields[#fields + 1] = ARGV[i]
end
redis.call('HSET', KEYS[1], unpack(fields))

local ttl = tonumber(ARGV[1]) or 0
if ttl > 0 then
  redis.call('EXPIRE', KEYS[1], ttl)
end
return 1
