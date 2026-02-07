import type { ReactNode } from 'react'
import { useId } from 'react'

type Option = {
  value: string
  label: string
  disabled?: boolean
}

type Props = {
  label: string
  value: string
  onChange: (value: string) => void
  options: Option[]
  helper?: string
  error?: string | null
  disabled?: boolean
  rightActions?: ReactNode
}

export default function SelectField({
  label,
  value,
  onChange,
  options,
  helper,
  error,
  disabled,
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
      <select
        id={id}
        className="field__input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value} disabled={opt.disabled}>
            {opt.label}
          </option>
        ))}
      </select>
      {error ? <div className="field__error">{error}</div> : null}
    </div>
  )
}

