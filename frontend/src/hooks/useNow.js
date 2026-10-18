import { useEffect, useState } from 'react';

/** Current server-corrected time, ticking every `interval` ms. */
export function useNow(offsetMs = 0, interval = 500) {
  const [now, setNow] = useState(() => Date.now() + offsetMs);
  useEffect(() => {
    setNow(Date.now() + offsetMs);
    const id = setInterval(() => setNow(Date.now() + offsetMs), interval);
    return () => clearInterval(id);
  }, [offsetMs, interval]);
  return now;
}
