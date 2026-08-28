import { useState } from "react";
import { AppHeader } from "./components/AppHeader.jsx";
import { Composer } from "./components/Composer.jsx";
import { EmptyState } from "./components/EmptyState.jsx";
import { VisualStage } from "./components/VisualStage.jsx";

export function App() {
  const [draft, setDraft] = useState("");

  return (
    <div className="app">
      <AppHeader />

      <main className="app-shell">
        <section className="interaction-stage" aria-label="AI 助手对话区">
          <EmptyState onPromptSelect={setDraft} />
          <Composer value={draft} onChange={setDraft} />
        </section>

        <VisualStage />
      </main>
    </div>
  );
}
