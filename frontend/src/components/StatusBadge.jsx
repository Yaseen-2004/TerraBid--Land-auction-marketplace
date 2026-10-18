import { STATUS_META } from '../utils/format.js';

export default function StatusBadge({ status }) {
  const meta = STATUS_META[status] || { label: status, tone: 'none' };
  return (
    <span className={`badge badge-${meta.tone}`}>
      {status === 'LIVE' && <span className="pulse-dot" />}
      {meta.label}
    </span>
  );
}
