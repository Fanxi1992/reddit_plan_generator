import type { RunStatus } from '../api/types'

type Props = {
  status: RunStatus | 'online' | 'offline' | 'unknown'
  text: string
}

const CLASS_MAP: Record<Props['status'], string> = {
  online: 'pill--ok',
  offline: 'pill--bad',
  unknown: 'pill--neutral',
  pending: 'pill--neutral',
  running: 'pill--neutral',
  succeeded: 'pill--ok',
  failed: 'pill--bad',
  cancelled: 'pill--neutral',
}

export default function StatusPill({ status, text }: Props) {
  return <span className={`pill ${CLASS_MAP[status]}`}>{text}</span>
}
