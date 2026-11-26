import { useState, type ReactNode } from "react";
import type { RelayTarget, RelayTargetBody } from "../api";
import { Button } from "../components/ui";
import { t } from "../i18n";

/**
 * 중계 서버의 방 하나를 보여 주고 정하는 줄. 보낼 곳과 받을 곳이 같이 쓴다(id 로 구분: "relay" / "relay-recv").
 * 방 화면에서 복사한 한 줄을 붙여 넣어도 되고, 서버(도메인)·포트·방·토큰을 칸마다 적어도 된다.
 * 토큰은 서버가 화면으로 돌려주지 않는다(적어 둔 것이 있다는 것만 안다).
 */
export function RelayTargetLine({
  id,
  title,
  none,
  target,
  example,
  tokenLabel,
  locked,
  onSave,
  onForget,
  children,
}: {
  id: string;
  title: string;
  /** 아직 정하지 않았을 때의 말 */
  none?: string;
  target: RelayTarget | null;
  /** 한 줄 칸에 흐리게 보여 줄 주소의 꼴 */
  example: string;
  tokenLabel: string;
  /** 주고받는 중이라 바꿀 수 없다 */
  locked?: boolean;
  /** 서버가 거절하면 이유를 던진다 */
  onSave: (body: RelayTargetBody) => Promise<void>;
  onForget: () => Promise<void>;
  /** 줄 끝에 붙일 단추(연결 확인 등) */
  children?: ReactNode;
}) {
  const [editing, setEditing] = useState(false);
  const [link, setLink] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("443");
  const [tls, setTls] = useState(true);
  const [room, setRoom] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pasted = Boolean(link.trim());
  /** 암호화 없이 내 컴퓨터 밖과 주고받게 되어 있는가 */
  const plain = target !== null && !target.tls && !["127.0.0.1", "localhost", "[::1]"].includes(target.host);

  const edit = () => {
    setLink("");
    setHost(target?.host ?? "");
    setPort(String(target?.port ?? 443));
    setTls(target?.tls ?? true);
    setRoom(target?.room ?? "");
    setToken("");
    setError("");
    setEditing(true);
  };
  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await work();
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const save = () => run(() => onSave(pasted ? { link: link.trim() } : { host: host.trim(), port: Number(port), tls, room: room.trim(), token: token.trim() }));

  return (
    <>
      <div className="relay-line">
        <span className="muted">{title}</span>
        {target ? <code title={target.url}>{target.url}</code> : <span className="muted">{none ?? t("relay.none")}</span>}
        <Button variant="link" onClick={edit} disabled={busy || locked} data-testid={`${id}-edit`}>
          {t(target ? "relay.change" : "relay.set")}
        </Button>
        {children}
      </div>
      {editing && (
        <form
          className="relay-form"
          data-testid={`${id}-form`}
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <label className="relay-wide">
            <span className="muted">{t("relay.link")}</span>
            <input value={link} onChange={(e) => setLink(e.target.value)} placeholder={example} autoComplete="off" spellCheck={false} data-testid={`${id}-link`} />
          </label>
          <p className="relay-wide muted">{t("relay.or")}</p>
          <label>
            <span className="muted">{t("relay.host")}</span>
            <input value={host} onChange={(e) => setHost(e.target.value)} placeholder="smjgallery.kr" disabled={pasted} autoComplete="off" spellCheck={false} data-testid={`${id}-host`} />
          </label>
          <label>
            <span className="muted">{t("relay.port")}</span>
            <input value={port} onChange={(e) => setPort(e.target.value)} inputMode="numeric" disabled={pasted} data-testid={`${id}-port`} />
          </label>
          <label>
            <span className="muted">{t("relay.room")}</span>
            <input value={room} onChange={(e) => setRoom(e.target.value)} disabled={pasted} autoComplete="off" spellCheck={false} data-testid={`${id}-room`} />
          </label>
          <label>
            <span className="muted">{tokenLabel}</span>
            <input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder={target?.token_set ? t("relay.token.kept") : ""} disabled={pasted} autoComplete="off" data-testid={`${id}-token`} />
          </label>
          <label className="relay-tick">
            <input type="checkbox" checked={tls} onChange={(e) => setTls(e.target.checked)} disabled={pasted} data-testid={`${id}-tls`} />
            {t("relay.tls")}
          </label>
          <div className="relay-wide relay-line">
            <Button type="submit" variant="secondary" disabled={busy || !(pasted || (host.trim() && room.trim()))} data-testid={`${id}-save`}>
              {t("relay.save")}
            </Button>
            <Button variant="link" onClick={() => setEditing(false)}>
              {t("saved.cancel")}
            </Button>
            {target && (
              <Button variant="link" onClick={() => void run(onForget)} disabled={busy} data-testid={`${id}-forget`}>
                {t("relay.forget")}
              </Button>
            )}
          </div>
          <p className="relay-wide muted">{t("relay.form.hint")}</p>
        </form>
      )}
      {plain && <p role="note">! {t("relay.plain")}</p>}
      {error && <p role="alert">! {error}</p>}
    </>
  );
}
