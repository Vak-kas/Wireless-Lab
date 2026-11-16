import { useId, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { useStore } from "../state/store";

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "utility" | "link" };

export function Button({ variant = "primary", className = "", type = "button", ...rest }: BtnProps) {
  const typo = variant === "utility" ? "t-button-utility" : variant === "link" ? "" : "t-body";
  return <button type={type} className={`btn btn-${variant} ${typo} ${className}`} {...rest} />;
}

const ICONS = { ok: "✓", warn: "!", error: "✕", info: "i" } as const;

/** 자물쇠 그림(잠긴 단계). 글꼴의 그림문자 대신 선 그림을 써서 색이 주변 글자를 따른다. */
export function LockIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
      <rect x="3.5" y="7" width="9" height="6.5" rx="1.5" />
      <path d="M5.5 7V5.2a2.5 2.5 0 0 1 5 0V7" />
    </svg>
  );
}

/** 상태는 색만으로 구분하지 않는다: 아이콘 + 문구를 같이 쓴다. */
export function Badge({ level, children }: { level: "ok" | "warn" | "error" | "info"; children: ReactNode }) {
  return (
    <span className="badge t-caption" data-level={level}>
      <span aria-hidden="true">{ICONS[level]}</span>
      {children}
    </span>
  );
}

export function Chip({
  selected,
  onSelect,
  children,
  disabled,
}: {
  selected: boolean;
  onSelect: () => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button type="button" className="chip t-caption" aria-pressed={selected} onClick={onSelect} disabled={disabled}>
      {children}
    </button>
  );
}

export function Fold({
  title,
  children,
  defaultOpen = false,
  testId,
}: {
  title: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  testId?: string;
}) {
  return (
    <details className="fold" open={defaultOpen || undefined} data-testid={testId}>
      <summary className="t-body">{title}</summary>
      <div className="fold-body">{children}</div>
    </details>
  );
}

export function Empty({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <p className="t-body">{children}</p>
      {action}
    </div>
  );
}

export function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: (props: { id: string; "aria-invalid"?: boolean; "aria-describedby"?: string }) => ReactNode;
}) {
  const id = useId();
  return (
    <label className="field" htmlFor={id}>
      <span className="t-caption">{label}</span>
      {children({ id, "aria-invalid": error ? true : undefined, "aria-describedby": error ? `${id}-err` : undefined })}
      {error && (
        <span className="error t-caption" id={`${id}-err`} role="alert">
          <span aria-hidden="true">✕ </span>
          {error}
        </span>
      )}
    </label>
  );
}

/** 전문 용어. 올리거나 초점을 주면 용어 사전의 한 줄 설명이 뜬다. 사전에 없으면 글자만 보여준다. */
export function Term({ k, children }: { k?: string; children: ReactNode }) {
  const { glossary } = useStore();
  const [open, setOpen] = useState(false);
  const id = useId();
  const entry = k ? glossary[k] : undefined;
  if (!entry) return <>{children}</>;
  return (
    <button
      type="button"
      className="term"
      aria-describedby={open ? id : undefined}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
    >
      {children}
      {open && (
        <span role="tooltip" id={id} className="tooltip t-caption">
          {entry.short}
        </span>
      )}
    </button>
  );
}
