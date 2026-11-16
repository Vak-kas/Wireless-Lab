import { t } from "./i18n";

export function App() {
  return (
    <main>
      <h1 className="t-display-lg">{t("app.name")}</h1>
      <p className="t-body">{t("app.tagline")}</p>
    </main>
  );
}
