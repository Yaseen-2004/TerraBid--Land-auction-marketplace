-- Release a lock only if it is still owned by ARGV[1].
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
