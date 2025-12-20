import type { ReactNode } from 'react'
import { useId } from 'react'

type Props = {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  helper?: string
  error?: string | null
  disabled?: boolean
  rows?: number
  monospace?: boolean
  rightActions?: ReactNode
}

export default function TextAreaField({
  label,
  value,
  onChange,
  placeholder,
  helper,
  error,
  disabled,
  rows = 10,
  monospace,
  rightActions,
}: Props) {
  const id = useId()

  return (
    <div className="field">
      <div className="field__header">
        <label className="field__label" htmlFor={id}>
          {label}
        </label>
        <div className="field__actions">{rightActions}</div>
      </div>
      {helper ? <div className="field__helper">{helper}</div> : null}
      <textarea
        id={id}
        className={`field__textarea ${monospace ? 'field__textarea--mono' : ''}`}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        rows={rows}
        spellCheck={false}
      />
      {error ? <div className="field__error">{error}</div> : null}
    </div>
  )
}
