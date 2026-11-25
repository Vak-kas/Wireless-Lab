import { useEffect, useState } from "react";
import type { ExportedFile, SavedState } from "../api";
import { Button } from "../components/ui";
import { t } from "../i18n";
import { useStore } from "../state/store";

/**
 * 녹화 파일을 다루는 두 조각.
 *  - SaveFolder: 녹화를 어디에 저장할지 보여 주고 바꾼다(운영체제의 폴더 고르는 창, 없으면 경로를 직접 적는다).
 *  - RecordFile: 방금 녹화한 파일을 파일 관리자(Finder)에서 보여 주고, 다른 형식으로 한 벌 더 만든다.
 * 서버에 이 기능이 없으면(공개판) 아무것도 그리지 않는다.
 */

const gb = (bytes: number) => (bytes / 1e9).toFixed(bytes < 1e10 ? 1 : 0);
/** macOS 에서는 "Finder", 그 밖에는 "폴더" */
const where = (platform: string | undefined) => t(platform === "darwin" ? "saved.finder" : "saved.files");

function useSaved(): [SavedState | null, (s: SavedState) => void] {
  const { api } = useStore();
  const [state, setState] = useState<SavedState | null>(null);
  useEffect(() => {
    let alive = true;
    void api.savedState().then(
      (s) => alive && setState(s),
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, [api]);
  return [state, setState];
}

export function SaveFolder({ disabled }: { disabled?: boolean }) {
  const { api } = useStore();
  const [state, setState] = useSaved();
  const [typing, setTyping] = useState(false);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!state) return null;

  const run = async (work: () => Promise<SavedState>, onFail?: () => void) => {
    setBusy(true);
    setError("");
    try {
      setState(await work());
      setTyping(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      onFail?.();
    } finally {
      setBusy(false);
    }
  };
  // 폴더 고르는 창을 띄울 수 있으면 그것으로, 없거나 실패하면 경로를 적는 칸을 연다
  const change = () => {
    if (!state.can_choose) return setTyping(true);
    void run(
      () => api.savedChoose(),
      () => setTyping(true),
    );
  };

  return (
    <div className="save-folder t-caption" data-testid="save-folder">
      <span className="muted">{t("saved.folder")}</span>
      <code title={state.folder}>{state.folder}</code>
      {state.free_bytes != null && <span className="muted">{t("saved.free", { gb: gb(state.free_bytes) })}</span>}
      <Button variant="link" onClick={change} disabled={busy || disabled} data-testid="save-folder-change">
        {busy ? t("saved.choosing") : t("saved.change")}
      </Button>
      {!state.is_default && (
        <Button variant="link" onClick={() => void run(() => api.savedFolder(null))} disabled={busy || disabled} data-testid="save-folder-default">
          {t("saved.to_default")}
        </Button>
      )}
      <Button variant="link" onClick={() => void api.savedReveal(state.folder).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))} data-testid="save-folder-open">
        {t("saved.open", { where: where(state.platform) })}
      </Button>
      {typing && (
        <form
          className="save-folder-type"
          onSubmit={(e) => {
            e.preventDefault();
            void run(() => api.savedFolder(path));
          }}
        >
          <input value={path} onChange={(e) => setPath(e.target.value)} placeholder={state.default} aria-label={t("saved.path")} data-testid="save-folder-path" />
          <Button variant="link" type="submit" disabled={busy || !path.trim()}>
            {t("saved.use")}
          </Button>
          <Button variant="link" onClick={() => setTyping(false)}>
            {t("saved.cancel")}
          </Button>
        </form>
      )}
      {error && (
        <span role="alert" className="save-folder-error">
          ! {error}
        </span>
      )}
    </div>
  );
}

export function RecordFile({ dataPath, metaPath, done }: { dataPath: string; metaPath?: string; done: boolean }) {
  const { api } = useStore();
  const [state] = useSaved();
  const [format, setFormat] = useState("cf32");
  const [busy, setBusy] = useState(false);
  const [made, setMade] = useState<ExportedFile | null>(null);
  const [error, setError] = useState("");
  if (!state) return null;
  const fail = (e: unknown) => setError(e instanceof Error ? e.message : String(e));
  const reveal = (path: string) => void api.savedReveal(path).catch(fail);
  const exportIt = async () => {
    if (!metaPath) return;
    setBusy(true);
    setError("");
    setMade(null);
    try {
      setMade(await api.savedExport(metaPath, format));
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="record-file t-caption" data-testid="record-file">
      <Button variant="link" onClick={() => reveal(dataPath)} data-testid="record-reveal">
        {t("saved.reveal", { where: where(state.platform) })}
      </Button>
      {done && metaPath && (
        <>
          <label className="record-export">
            <span className="muted">{t("saved.export.as")}</span>
            <select value={format} onChange={(e) => setFormat(e.target.value)} disabled={busy} data-testid="record-format">
              {state.formats.map((f) => (
                <option key={f} value={f}>
                  {t(`saved.format.${f}`)}
                </option>
              ))}
            </select>
          </label>
          <Button variant="link" onClick={() => void exportIt()} disabled={busy} data-testid="record-export">
            {busy ? t("saved.export.busy") : t("saved.export")}
          </Button>
        </>
      )}
      {made && (
        <p className="record-made" data-testid="record-made">
          {t("saved.export.done", { mb: (made.bytes / 1e6).toFixed(1) })} <code>{made.path}</code>{" "}
          <Button variant="link" onClick={() => reveal(made.path)}>
            {t("saved.reveal", { where: where(state.platform) })}
          </Button>
          {made.format !== "wav" && (
            <>
              <br />
              <span className="muted">{t("saved.export.note", { rate: (made.sample_rate_hz / 1e6).toString(), center: (made.center_freq_hz / 1e6).toString() })}</span>
            </>
          )}
        </p>
      )}
      {error && <p role="alert">! {error}</p>}
    </div>
  );
}
