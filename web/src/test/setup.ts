// jsdom lacks canvas and scrolling; ECharts falls back gracefully when getContext returns null.
HTMLCanvasElement.prototype.getContext = (() => null) as typeof HTMLCanvasElement.prototype.getContext;
window.scrollTo = (() => undefined) as typeof window.scrollTo;
