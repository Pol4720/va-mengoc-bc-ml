// Deck list and slide viewer: keyboard navigation, fullscreen, speaker notes, handout/print mode.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Chart } from "../components/Chart";
import { Legend } from "../components/ui";
import { useLang } from "../i18n";
import { buildDecks, type Deck, type Slide } from "../slides/decks";
import { routeHash, useBundle } from "../state";
import { useTokens } from "../theme";

export function Slides({ deckId, slide }: { deckId?: string; slide?: number }) {
  const { bundle } = useBundle();
  const L = useLang();
  const t = useTokens();
  const decks = useMemo(() => buildDecks(bundle, L, t), [bundle, L, t]);
  const deck = decks.find((d) => d.id === deckId);
  if (!deck) return <DeckList decks={decks} />;
  return <Viewer deck={deck} index={Math.min(Math.max((slide ?? 1) - 1, 0), deck.slides.length - 1)} />;
}

function DeckList({ decks }: { decks: Deck[] }) {
  const { tr } = useLang();
  return (
    <>
      <header className="page-head">
        <div className="eyebrow">{tr("Socialización", "Outreach")}</div>
        <h1>{tr("Presentaciones para las reuniones de expertos", "Decks for the expert meetings")}</h1>
        <p className="lede">
          {tr(
            "Presentaciones generadas a partir del release: se actualizan solas cuando cambian los resultados. Use las flechas para avanzar, F para pantalla completa y N para las notas del orador.",
            "Decks generated from the release: they update themselves when results change. Use the arrow keys to advance, F for fullscreen and N for speaker notes.",
          )}
        </p>
      </header>
      <div className="deck-list">
        {decks.map((d) => (
          <a key={d.id} className="tile-link" href={routeHash({ page: "slides", deck: d.id, slide: 1 })}>
            <div className="eyebrow">{tr(`${d.slides.length} diapositivas`, `${d.slides.length} slides`)}</div>
            <h3>{d.title}</h3>
            <p>{d.description}</p>
          </a>
        ))}
      </div>
    </>
  );
}

function SlideView({ s, n, total, back }: { s: Slide; n: number; total: number; back: boolean }) {
  const { tr } = useLang();
  const { bundle } = useBundle();
  const cls = `slide${s.layout === "title" ? " title-slide" : ""}${back ? " back" : ""}`;
  return (
    <div className={cls} aria-roledescription={tr("diapositiva", "slide")} aria-label={`${n} / ${total}: ${s.title}`}>
      {s.kicker ? <div className="kicker">{s.kicker}</div> : null}
      <h2>{s.title}</h2>
      {s.sub ? <div className="slide-sub">{s.sub}</div> : null}
      {s.layout === "bullets" && s.bullets ? (
        <div className="slide-body">
          <ul>
            {s.bullets.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {s.layout === "split" && s.bullets ? (
        <div className="slide-body">
          <ul style={{ columns: s.bullets.length > 5 ? 2 : 1, display: "block" }}>
            {s.bullets.map((b, i) => (
              <li key={i} style={{ marginBottom: "1.4cqh", breakInside: "avoid" }}>
                {b}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {s.layout === "kpis" && s.kpis ? (
        <div className="slide-body" style={{ alignContent: "center" }}>
          <div className="slide-kpis">
            {s.kpis.map((k) => (
              <div key={k.l}>
                <div className="v">{k.v}</div>
                <div className="l">{k.l}</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {s.layout === "chart" && s.chart ? (
        <div className={s.chart.legend ? "slide-body slide-chart-body" : "slide-body"}>
          {s.chart.legend ? <Legend items={s.chart.legend} /> : null}
          <Chart option={s.chart.option} label={s.chart.label} height="100%" className="slide-chart" />
        </div>
      ) : null}
      <div className="slide-foot">
        <span>VA-MENGOC-BC{bundle.meta.synthetic ? tr(" · datos sintéticos", " · synthetic data") : ""}</span>
        <span>
          {n} / {total}
        </span>
      </div>
      <div className="slide-progress" style={{ width: `${(n / total) * 100}%` }} />
    </div>
  );
}

function Viewer({ deck, index }: { deck: Deck; index: number }) {
  const { tr } = useLang();
  const root = useRef<HTMLDivElement>(null);
  const [notes, setNotes] = useState(false);
  const [handout, setHandout] = useState(false);
  // Direction of the last move, derived from the previous index (slide-in from the left when going back).
  const [last, setLast] = useState(index);
  const [back, setBack] = useState(false);
  if (index !== last) {
    setBack(index < last);
    setLast(index);
  }
  const total = deck.slides.length;
  const go = useCallback(
    (i: number) => {
      const n = Math.min(Math.max(i, 0), total - 1);
      window.location.hash = routeHash({ page: "slides", deck: deck.id, slide: n + 1 });
    },
    [deck.id, total],
  );
  const fullscreen = useCallback(() => {
    const el = root.current;
    if (!el) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void el.requestFullscreen?.().catch(() => undefined);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || e.altKey || e.ctrlKey || e.metaKey) return;
      if (["ArrowRight", "PageDown", " "].includes(e.key)) {
        e.preventDefault();
        go(index + 1);
      } else if (["ArrowLeft", "PageUp"].includes(e.key)) {
        e.preventDefault();
        go(index - 1);
      } else if (e.key === "Home") go(0);
      else if (e.key === "End") go(total - 1);
      else if (e.key === "f" || e.key === "F") fullscreen();
      else if (e.key === "n" || e.key === "N") setNotes((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, index, total, fullscreen]);

  const s = deck.slides[index];
  if (!s) return null;

  if (handout) {
    return (
      <div className="handout">
        <div className="deck-bar no-print">
          <button type="button" className="btn" onClick={() => setHandout(false)}>
            ← {tr("Volver a la presentación", "Back to the deck")}
          </button>
          <button type="button" className="btn primary" onClick={() => window.print()}>
            {tr("Imprimir o guardar PDF", "Print or save as PDF")}
          </button>
        </div>
        <div className="handout-list">
          {deck.slides.map((sl, i) => (
            <div key={i} className="slide-frame">
              <SlideView s={sl} n={i + 1} total={total} back={false} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="deck" ref={root}>
      <div className="slide-frame">
        <SlideView key={index} s={s} n={index + 1} total={total} back={back} />
      </div>
      <div className="deck-bar">
        <div style={{ display: "flex", gap: 6 }}>
          <a className="btn small" href={routeHash({ page: "slides" })}>
            {tr("Todas", "All decks")}
          </a>
          <button type="button" className="btn small" onClick={() => go(index - 1)} disabled={index === 0} aria-label={tr("Anterior", "Previous")}>
            ←
          </button>
          <button type="button" className="btn small" onClick={() => go(index + 1)} disabled={index === total - 1} aria-label={tr("Siguiente", "Next")}>
            →
          </button>
        </div>
        <span style={{ color: "var(--muted)", fontSize: "0.85rem" }} aria-live="polite">
          {index + 1} / {total}
        </span>
        <div style={{ display: "flex", gap: 6 }}>
          <button type="button" className="btn small" onClick={() => setNotes((v) => !v)} aria-pressed={notes}>
            {tr("Notas", "Notes")} (N)
          </button>
          <button type="button" className="btn small" onClick={fullscreen}>
            {tr("Pantalla completa", "Fullscreen")} (F)
          </button>
          <button type="button" className="btn small" onClick={() => setHandout(true)}>
            {tr("Folleto / PDF", "Handout / PDF")}
          </button>
        </div>
      </div>
      {notes ? (
        <aside className="notes" aria-label={tr("Notas del orador", "Speaker notes")}>
          {s.notes}
        </aside>
      ) : null}
    </div>
  );
}
