/** Quick follow-ups. Each submits its own word as the next turn. */
export const CHIPS = [
  "deeper",
  "technical",
  "why",
  "failure",
  "debug",
  "scale",
  "security",
  "screen",
  "push",
] as const;

interface Props {
  onSelect: (chip: string) => void;
  disabled: boolean;
}

export function CommandChips({ onSelect, disabled }: Props) {
  return (
    <div className="chips">
      {CHIPS.map((chip) => (
        <button
          key={chip}
          className="chip"
          disabled={disabled}
          onClick={() => onSelect(chip)}
          type="button"
        >
          {chip}
        </button>
      ))}
    </div>
  );
}
