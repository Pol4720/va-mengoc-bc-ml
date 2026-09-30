"""Local lab API: lets the web application run and customise the pipeline on this machine.

Security model
--------------
* Bound to the loopback interface by ``vamengoc serve`` (never exposed on a network).
* Every mutating or data-returning request must carry the per-process token
  (``X-Lab-Token``), printed in the terminal at start-up; a custom header also
  forces a CORS preflight, so other websites cannot trigger runs (CSRF).
* CORS is limited to local development origins and the project's GitHub Pages
  origin; Private Network Access preflights are answered explicitly.
* Only disclosure-controlled releases and job metadata are served — never raw
  or curated records. Every experiment release is verified before it is served.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import secrets
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from vamengoc import __version__
from vamengoc.config import Project, deep_merge

__all__ = ["TUNABLES", "app", "create_app"]

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "https://pol4720.github.io",
]

# Parameters exposed in the web UI: dotted path, type, bounds and bilingual help.
TUNABLES: list[dict[str, Any]] = [
    {
        "path": "analysis.analytic_year_from",
        "type": "enum",
        "options": ["vaccination_date", "notification_date", "file_year"],
        "es": "Fecha que define el año analítico",
        "en": "Date defining the analytic year",
    },
    {
        "path": "analysis.study_years",
        "type": "int_range",
        "min": 2010,
        "max": 2030,
        "es": "Ventana de estudio (años)",
        "en": "Study window (years)",
    },
    {
        "path": "analysis.infant_comparator_max_age_months",
        "type": "int",
        "min": 2,
        "max": 23,
        "es": "Edad máxima del comparador activo (meses)",
        "en": "Active comparator maximum age (months)",
    },
    {
        "path": "analysis.disproportionality.min_reports",
        "type": "int",
        "min": 1,
        "max": 20,
        "es": "Mínimo de notificaciones para señal",
        "en": "Minimum reports for a signal",
    },
    {
        "path": "analysis.disproportionality.eb05_threshold",
        "type": "float",
        "min": 1.0,
        "max": 5.0,
        "es": "Umbral EB05",
        "en": "EB05 threshold",
    },
    {
        "path": "analysis.lca.k_range",
        "type": "int_range",
        "min": 1,
        "max": 10,
        "es": "Número de clases latentes evaluadas",
        "en": "Latent classes evaluated",
    },
    {
        "path": "analysis.qc.ewma_lambda",
        "type": "float",
        "min": 0.05,
        "max": 1.0,
        "es": "Lambda del gráfico EWMA",
        "en": "EWMA lambda",
    },
    {
        "path": "analysis.qc.mspc_alpha",
        "type": "float",
        "min": 0.001,
        "max": 0.1,
        "es": "Alfa de los límites MSPC",
        "en": "MSPC control-limit alpha",
    },
    {
        "path": "analysis.qc.equivalence_margin_fraction",
        "type": "float",
        "min": 0.01,
        "max": 0.5,
        "es": "Margen de equivalencia (fracción de la ventana)",
        "en": "Equivalence margin (window fraction)",
    },
    {
        "path": "analysis.qc_safety.gee_cov_struct",
        "type": "enum",
        "options": ["exchangeable", "independence"],
        "es": "Correlación de trabajo GEE",
        "en": "GEE working correlation",
    },
    {
        "path": "analysis.qc_safety.permutation_tests",
        "type": "int",
        "min": 0,
        "max": 2000,
        "es": "Permutaciones de la prueba de valor incremental",
        "en": "Permutations (incremental value)",
    },
    {
        "path": "analysis.linkage.fuzzy_threshold",
        "type": "float",
        "min": 70,
        "max": 100,
        "es": "Umbral de enlace aproximado de lotes",
        "en": "Fuzzy lot-linkage threshold",
    },
    {
        "path": "analysis.linkage.allow_fuzzy",
        "type": "bool",
        "es": "Permitir enlace aproximado",
        "en": "Allow fuzzy linkage",
    },
    {
        "path": "sdc.min_cell",
        "type": "int",
        "min": 3,
        "max": 20,
        "es": "Tamaño mínimo de celda publicable",
        "en": "Minimum publishable cell size",
    },
    {
        "path": "analysis.seed",
        "type": "int",
        "min": 0,
        "max": 2**31 - 1,
        "es": "Semilla aleatoria",
        "en": "Random seed",
    },
]


class RunRequest(BaseModel):
    source: Literal["synthetic", "raw"] = "synthetic"
    overrides: dict[str, Any] = Field(default_factory=dict)
    synthetic_scale: float = Field(0.1, gt=0, le=2)
    synthetic_seed: int = 20260930
    regenerate_synthetic: bool = True


@dataclass
class Job:
    id: str
    request: dict[str, Any]
    status: str = "queued"  # queued | running | done | failed
    created: str = field(default_factory=lambda: dt.datetime.now(dt.UTC).isoformat(timespec="seconds"))
    finished: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    release_dir: str | None = None
    verification: dict[str, Any] | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "created": self.created,
            "finished": self.finished,
            "request": self.request,
            "steps": self.steps[-50:],
            "error": self.error,
            "verification": self.verification,
            "has_bundle": self.release_dir is not None,
        }


def _validate_overrides(overrides: dict[str, Any]) -> dict[str, Any]:
    """Accept only whitelisted parameters (dotted paths from TUNABLES)."""
    allowed = {t["path"] for t in TUNABLES}
    flat: dict[str, Any] = {}

    def walk(node: dict[str, Any], prefix: str) -> None:
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                walk(v, path)
            else:
                flat[path] = v

    walk(overrides, "")
    bad = sorted(set(flat) - allowed)
    if bad:
        raise HTTPException(status_code=422, detail=f"parameters not tunable from the UI: {bad}")
    nested: dict[str, Any] = {}
    for path, value in flat.items():
        node = nested
        parts = path.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value
    return nested


def create_app(project_root: Path | None = None, token: str | None = None) -> FastAPI:
    base = Project(project_root)
    lab_token = token or os.environ.get("VAMENGOC_LAB_TOKEN") or secrets.token_urlsafe(24)
    jobs: dict[str, Job] = {}
    lock = threading.Lock()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vamengoc-job")
    api = FastAPI(
        title="VA-MENGOC-BC local lab", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    api.state.token = lab_token
    api.state.jobs = jobs
    api.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["X-Lab-Token", "Content-Type"],
    )

    @api.middleware("http")
    async def private_network(request: Request, call_next: Any) -> Response:
        response: Response = await call_next(request)
        if request.headers.get("access-control-request-private-network") == "true":
            response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

    def require_token(x_lab_token: str | None = Header(default=None)) -> None:
        if not x_lab_token or not secrets.compare_digest(x_lab_token, lab_token):
            raise HTTPException(status_code=401, detail="missing or invalid X-Lab-Token")

    @api.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "raw_data_present": any(base.raw_dir.glob("*.xls*")),
            "releases": sorted(p.name for p in base.release_dir.glob("*") if (p / "manifest.json").is_file()),
        }

    @api.get("/api/tunables", dependencies=[Depends(require_token)])
    def tunables() -> dict[str, Any]:
        cfg = base.raw_config

        def get(path: str) -> Any:
            node: Any = cfg
            for p in path.split("."):
                node = node[p]
            return node

        return {"tunables": [{**t, "value": get(t["path"])} for t in TUNABLES]}

    @api.get("/api/releases/{origin}/bundle", dependencies=[Depends(require_token)])
    def release_bundle(origin: Literal["public", "synthetic"]) -> Response:
        path = base.release_dir / origin / "web" / "bundle.json"
        if not path.is_file():
            raise HTTPException(status_code=404, detail=f"release '{origin}' not built")
        return Response(content=path.read_bytes(), media_type="application/json")

    def run_job(job: Job) -> None:
        from vamengoc.pipeline import run_pipeline
        from vamengoc.release.verify import verify_release
        from vamengoc.synth import generate_synthetic_dataset

        job.status = "running"
        try:
            req = RunRequest.model_validate(job.request)
            exp_root = base.runs_dir / "lab" / job.id
            over = deep_merge(
                _validate_overrides(req.overrides),
                {"paths": {"release_dir": str(exp_root / "release"), "curated_dir": str(exp_root / "curated")}},
            )
            project = Project(base.root, overrides=over)
            if req.source == "synthetic":
                src = exp_root / "synthetic-input"
                job.steps.append({"step": "generate_synthetic", "scale": req.synthetic_scale})
                generate_synthetic_dataset(src, scale=req.synthetic_scale, seed=req.synthetic_seed)
            else:
                src = base.raw_dir
            outputs = run_pipeline(project, src, command="lab")
            job.steps.extend(outputs.run.steps)
            if outputs.release_dir is not None:
                rep = verify_release(project, outputs.release_dir)
                job.verification = {"ok": rep.ok, "errors": rep.errors[:20], "files": rep.checked_files}
                if rep.ok:
                    job.release_dir = str(outputs.release_dir)
            job.status = "done" if job.release_dir else "failed"
            if not job.release_dir:
                job.error = "release verification failed; results withheld"
        except Exception as exc:  # report any failure to the UI
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.steps.append({"step": "traceback", "detail": traceback.format_exc(limit=5)[-2000:]})
        finally:
            job.finished = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")

    @api.post("/api/runs", dependencies=[Depends(require_token)], status_code=202)
    def submit(req: RunRequest) -> dict[str, Any]:
        _validate_overrides(req.overrides)
        if req.source == "raw" and not any(base.raw_dir.glob("*.xls*")):
            raise HTTPException(status_code=409, detail="no raw files in data/raw")
        job = Job(id=uuid.uuid4().hex[:12], request=req.model_dump())
        with lock:
            jobs[job.id] = job
        executor.submit(run_job, job)
        return job.public()

    @api.get("/api/runs", dependencies=[Depends(require_token)])
    def list_runs() -> list[dict[str, Any]]:
        return [j.public() for j in sorted(jobs.values(), key=lambda j: j.created, reverse=True)]

    @api.get("/api/runs/{job_id}", dependencies=[Depends(require_token)])
    def get_run(job_id: str) -> dict[str, Any]:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return job.public()

    @api.get("/api/runs/{job_id}/bundle", dependencies=[Depends(require_token)])
    def run_bundle(job_id: str) -> Response:
        job = jobs.get(job_id)
        if job is None or job.release_dir is None:
            raise HTTPException(status_code=404, detail="no verified bundle for this job")
        data = json.loads((Path(job.release_dir) / "web" / "bundle.json").read_text(encoding="utf-8"))
        data.setdefault("meta", {})["lab_job"] = job.id
        return Response(content=json.dumps(data, ensure_ascii=False), media_type="application/json")

    return api


app = create_app()
