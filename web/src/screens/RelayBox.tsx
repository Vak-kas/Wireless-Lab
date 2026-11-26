import { useCallback, useEffect, useState } from "react";
import type { RelayCheck, RelayLink, RelayState, StreamTapState } from "../api";
import { Button } from "../components/ui";
import { t } from "../i18n";
import { useStore } from "../state/store";

/**
 * 실시간 중계: 받고 있는 I/Q 나 저장한 파일을 중계 서버의 방으로 보낸다(규격은 docs/relay-protocol.md).
 *  - 어디로 보내는지(서버·포트·방)를 보여 주고 바꾼다. 방 화면에서 복사한 한 줄을 붙여 넣어도 되고 칸마다 적어도 된다.
 *  - live 를 주면 "받는 것을 중계"하는 단추가, file 을 주면 "이 파일을 중계로 보내기" 단추가 나온다.
 * 보내는 것은 사람이 단추를 누를 때뿐이다. 서버에 이 기능이 없으면(공개판) 아무것도 그리지 않는다.
 */

const POLL_MS = 500;
const mb = (bytes: number | undefined) => ((bytes ?? 0) / 1e6).toFixed(1);
const minutes = (s: number | null | undefined) =>
  s == null ? "?" : String(Math.max(0, Math.round(s / 60)));
const text = (e: unknown) => (e instanceof Error ? e.message : String(e));

interface Live {
  /** 받는 중인가 */
  running: boolean;
  /** 꽂혀 있는 중계 풀이의 상태(없으면 중계하지 않는 중) */
  tap?: StreamTapState;
  onToggle: (on: boolean) => void;
}

/** 연결 하나의 상태 한 줄: 보낸 양, 받는 쪽 수, 버린 양 */
function LinkLine({ link, seconds }: { link: RelayLink; seconds?: string }) {
  const lost = (link.dropped_bytes ?? 0) + (link.relay_dropped_bytes ?? 0);
  return (
    <span data-testid="relay-status">
      {t(
        link.connected
          ? "relay.status.on"
          : link.error
            ? "relay.status.off"
            : "relay.status.done",
      )}{" "}
      · {seconds ? `${seconds} · ` : ""}
      {t("relay.status.sent", { mb: mb(link.sent_bytes) })} ·{" "}
      {t("relay.status.receivers", { n: link.receivers ?? 0 })}
      {lost > 0 ? ` · ${t("relay.status.lost", { mb: mb(lost) })}` : ""}
    </span>
  );
}

export function RelayBox({ live, file }: { live?: Live; file?: string }) {
  const { api } = useStore();
  const [state, setState] = useState<RelayState | null>(null);
  const [editing, setEditing] = useState(false);
  const [link, setLink] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("443");
  const [tls, setTls] = useState(true);
  const [room, setRoom] = useState("");
  const [token, setToken] = useState("");
  const [loop, setLoop] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [checked, setChecked] = useState<RelayCheck | null>(null);

  useEffect(() => {
    let alive = true;
    void api.relayState().then(
      (s) => alive && setState(s),
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, [api]);

  const jobRunning = state?.job?.running ?? false;
  useEffect(() => {
    if (!jobRunning) return;
    const timer = setInterval(() => {
      api.relayState().then(setState, () => undefined);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [api, jobRunning]);

  const run = useCallback(
    async (work: () => Promise<RelayState>): Promise<boolean> => {
      setBusy(true);
      setError("");
      try {
        setState(await work());
        return true;
      } catch (e) {
        setError(text(e));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  if (!state?.available) return null;
  const target = state.target;
  const job = state.job;
  const relaying = Boolean(live?.running && live.tap && !live.tap.ended);
  const sending = relaying || jobRunning;
  /** 암호화 없이 내 컴퓨터 밖으로 보내게 되어 있는가 */
  const open =
    target !== null &&
    !target.tls &&
    !["127.0.0.1", "localhost", "[::1]"].includes(target.host);

  const edit = () => {
    setLink("");
    setHost(target?.host ?? "");
    setPort(String(target?.port ?? 443));
    setTls(target?.tls ?? true);
    setRoom(target?.room ?? "");
    setToken("");
    setChecked(null);
    setError("");
    setEditing(true);
  };
  const save = async () => {
    const body = link.trim()
      ? { link: link.trim() }
      : {
          host: host.trim(),
          port: Number(port),
          tls,
          room: room.trim(),
          token: token.trim(),
        };
    if (await run(() => api.relayTarget(body))) setEditing(false);
  };
  const check = async () => {
    setBusy(true);
    setError("");
    setChecked(null);
    try {
      setChecked(await api.relayCheck());
    } catch (e) {
      setError(text(e));
    } finally {
      setBusy(false);
    }
  };
  /** 이 파일이 지금 보내고 있는(또는 방금 보낸) 그 파일인가: 설명 파일과 데이터 파일은 이름의 끝만 다르다 */
  const stem = (p: string) => p.replace(/\.sigmf-(meta|data)$/, "");
  const mine = job && file ? stem(job.meta_path) === stem(file) : false;

  return (
    <div className="relay-box t-caption" data-testid="relay-box">
      <div className="relay-line">
        <span className="muted">{t("relay.title")}</span>
        {target ? (
          <code title={target.url}>{target.url}</code>
        ) : (
          <span className="muted">{t("relay.none")}</span>
        )}
        <Button
          variant="link"
          onClick={edit}
          disabled={busy || sending}
          data-testid="relay-edit"
        >
          {t(target ? "relay.change" : "relay.set")}
        </Button>
        {target && (
          <Button
            variant="link"
            onClick={() => void check()}
            disabled={busy || sending}
            data-testid="relay-check"
          >
            {t("relay.check")}
          </Button>
        )}
      </div>

      {editing && (
        <form
          className="relay-form"
          data-testid="relay-form"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <label className="relay-wide">
            <span className="muted">{t("relay.link")}</span>
            <input
              value={link}
              onChange={(e) => setLink(e.target.value)}
              placeholder="wss://smjgallery.kr/relay/ws/…/iq/send?token=…"
              autoComplete="off"
              spellCheck={false}
              data-testid="relay-link"
            />
          </label>
          <p className="relay-wide muted">{t("relay.or")}</p>
          <label>
            <span className="muted">{t("relay.host")}</span>
            <input
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="smjgallery.kr"
              disabled={Boolean(link.trim())}
              autoComplete="off"
              spellCheck={false}
              data-testid="relay-host"
            />
          </label>
          <label>
            <span className="muted">{t("relay.port")}</span>
            <input
              value={port}
              onChange={(e) => setPort(e.target.value)}
              inputMode="numeric"
              disabled={Boolean(link.trim())}
              data-testid="relay-port"
            />
          </label>
          <label>
            <span className="muted">{t("relay.room")}</span>
            <input
              value={room}
              onChange={(e) => setRoom(e.target.value)}
              disabled={Boolean(link.trim())}
              autoComplete="off"
              spellCheck={false}
              data-testid="relay-room"
            />
          </label>
          <label>
            <span className="muted">{t("relay.token")}</span>
            <input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder={target?.token_set ? t("relay.token.kept") : ""}
              disabled={Boolean(link.trim())}
              autoComplete="off"
              data-testid="relay-token"
            />
          </label>
          <label className="relay-tick">
            <input
              type="checkbox"
              checked={tls}
              onChange={(e) => setTls(e.target.checked)}
              disabled={Boolean(link.trim())}
              data-testid="relay-tls"
            />
            {t("relay.tls")}
          </label>
          <div className="relay-wide relay-line">
            <Button
              type="submit"
              variant="secondary"
              disabled={busy || !(link.trim() || (host.trim() && room.trim()))}
              data-testid="relay-save"
            >
              {t("relay.save")}
            </Button>
            <Button variant="link" onClick={() => setEditing(false)}>
              {t("saved.cancel")}
            </Button>
            {target && (
              <Button
                variant="link"
                onClick={() =>
                  void run(() => api.relayForget()).then(
                    (ok) => ok && setEditing(false),
                  )
                }
                disabled={busy}
                data-testid="relay-forget"
              >
                {t("relay.forget")}
              </Button>
            )}
          </div>
          <p className="relay-wide muted">{t("relay.form.hint")}</p>
        </form>
      )}

      {open && <p role="note">! {t("relay.plain")}</p>}
      {checked && (
        <p data-testid="relay-checked">
          ✓{" "}
          {t("relay.checked", {
            limit: mb(checked.rate_limit ?? 0),
            n: checked.receivers,
            min: minutes(checked.expires_in),
          })}
        </p>
      )}

      {live && target && (
        <div className="relay-line">
          <Button
            variant="secondary"
            onClick={() => live.onToggle(!relaying)}
            disabled={!live.running || busy}
            aria-pressed={relaying}
            data-testid="relay-live-toggle"
          >
            {relaying
              ? `■ ${t("relay.live.stop")}`
              : `▲ ${t("relay.live.start")}`}
          </Button>
          {!live.running && (
            <span className="muted">{t("relay.live.idle")}</span>
          )}
          {live.tap && live.tap.connected !== undefined && (
            <LinkLine
              link={{
                ...live.tap,
                connected: Boolean(live.tap.connected) && relaying,
                error: relaying ? live.tap.error || "-" : "", // 켜 둔 동안 붙어 있지 않으면 "연결 안 됨", 끈 뒤에는 "보내기 끝남"
                sent_bytes: live.tap.sent_bytes ?? 0,
                dropped_bytes: live.tap.dropped_bytes ?? 0,
              }}
            />
          )}
          {relaying && live.tap?.need_bps ? (
            <span className="muted">
              {t("relay.need", {
                mb: mb(live.tap.need_bps),
                mbit: ((live.tap.need_bps * 8) / 1e6).toFixed(0),
              })}
            </span>
          ) : null}
        </div>
      )}

      {file && target && (
        <div className="relay-line">
          {jobRunning ? (
            <Button
              variant="secondary"
              onClick={() => void run(() => api.relayFileStop())}
              disabled={busy}
              data-testid="relay-file-stop"
            >
              ■ {t("relay.file.stop")}
            </Button>
          ) : (
            <>
              <Button
                variant="secondary"
                onClick={() => void run(() => api.relayFile(file, loop))}
                disabled={busy}
                data-testid="relay-file-start"
              >
                ▲ {t("relay.file.start")}
              </Button>
              <label className="relay-tick">
                <input
                  type="checkbox"
                  checked={loop}
                  onChange={(e) => setLoop(e.target.checked)}
                  data-testid="relay-file-loop"
                />
                {t("relay.file.loop")}
              </label>
            </>
          )}
          {job && (jobRunning || mine) && (
            <LinkLine
              link={{ ...job, connected: job.connected && job.running }}
              seconds={t("relay.file.at", {
                s: job.seconds.toFixed(1),
                total: job.total_s.toFixed(1),
              })}
            />
          )}
          {job && jobRunning && !mine && (
            <span className="muted">
              {t("relay.file.other", { name: job.name })}
            </span>
          )}
        </div>
      )}
      {job?.error && (jobRunning || mine) && <p role="alert">! {job.error}</p>}
      {error && <p role="alert">! {error}</p>}
    </div>
  );
}
