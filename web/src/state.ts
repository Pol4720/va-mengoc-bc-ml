// App-wide state shared through context: the active results bundle and its origin.

import { createContext, useContext } from "react";
import type { Bundle } from "./data/bundle";

export interface BundleState {
  bundle: Bundle;
  /** "release" for the published bundle, or the lab job id when results come from the local lab. */
  origin: string;
  setLabBundle: (b: Bundle | null) => void;
}

export const BundleContext = createContext<BundleState | null>(null);

export function useBundle(): BundleState {
  const s = useContext(BundleContext);
  if (!s) throw new Error("useBundle outside BundleContext");
  return s;
}

export type Page = "home" | "pv" | "lots" | "data" | "lab" | "slides";

export interface Route {
  page: Page;
  deck?: string;
  slide?: number;
}

const PAGES: Page[] = ["home", "pv", "lots", "data", "lab", "slides"];

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const page = (parts[0] ?? "home") as Page;
  if (!PAGES.includes(page)) return { page: "home" };
  if (page === "slides") {
    const n = Number(parts[2]);
    return { page, deck: parts[1], slide: Number.isInteger(n) && n > 0 ? n : undefined };
  }
  return { page };
}

export function routeHash(r: Route): string {
  if (r.page === "home") return "#/";
  if (r.page === "slides" && r.deck) return `#/slides/${r.deck}${r.slide ? `/${r.slide}` : ""}`;
  return `#/${r.page}`;
}
