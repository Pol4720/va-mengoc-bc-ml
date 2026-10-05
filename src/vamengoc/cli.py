"""Command-line interface: ``vamengoc <command>``.

Typical Phase 1 session (inside the controlled environment)::

    vamengoc keygen                 # once: secret pseudonymisation key outside the repo
    vamengoc schema-check           # inspect the layout of new raw files (no analysis)
    vamengoc run                    # full pipeline on data/raw -> release/public
    vamengoc release verify public  # disclosure-control guard before committing

Development / demonstration::

    vamengoc demo --scale 0.3       # synthetic data -> release/synthetic
"""

from __future__ import annotations

import json
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

from vamengoc import __version__
from vamengoc.config import Project

app = typer.Typer(add_completion=False, no_args_is_help=True, help="VA-MENGOC-BC reproducible analytics.")
release_app = typer.Typer(no_args_is_help=True, help="Public release utilities.")
app.add_typer(release_app, name="release")
# Wide, non-wrapping output so that file names and paths stay greppable in logs and CI.
console = Console(width=160, soft_wrap=True)


def _parse_overrides(items: list[str] | None) -> dict[str, Any]:
    """``--set analysis.seed=1 --set sdc.min_cell=10`` → nested dict (YAML-typed values)."""
    out: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            msg = f"override must be key=value, got {item!r}"
            raise typer.BadParameter(msg)
        key, raw = item.split("=", 1)
        value = yaml.safe_load(raw)
        node = out
        parts = key.strip().split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value
    return out


def _write_secret(path: Path, content: str, force: bool) -> None:
    if path.exists() and not force:
        console.print(f"[yellow]{path} already exists (use --force to replace).[/yellow]")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content + "\n")
    console.print(f"[green]Wrote {path} (permissions 600). Back it up securely; never commit it.[/green]")


@app.command()
def version() -> None:
    """Print the package version."""
    console.print(__version__)


@app.command()
def keygen(
    fernet: Annotated[bool, typer.Option(help="Also create the curated-layer encryption key.")] = False,
    force: Annotated[bool, typer.Option(help="Overwrite existing keys.")] = False,
) -> None:
    """Create the secret HMAC pseudonymisation key (and optionally a Fernet key)."""
    project = Project()
    sec = project.config.security
    _write_secret(Path(sec.hmac_key_file).expanduser(), secrets.token_hex(32), force)
    if fernet:
        from vamengoc.security.crypto import generate_key

        _write_secret(Path(sec.fernet_key_file).expanduser(), generate_key().decode("ascii"), force)


@app.command()
def synth(
    out: Annotated[Path | None, typer.Option(help="Output directory (default: data/synthetic).")] = None,
    scale: Annotated[float, typer.Option(help="Fraction of the real annual volume (1.0 ≈ 7 700/year).")] = 1.0,
    seed: Annotated[int, typer.Option()] = 20260930,
) -> None:
    """Generate the synthetic input files (never real data)."""
    from vamengoc.synth import generate_synthetic_dataset

    project = Project()
    target = out or project.synthetic_dir
    ds = generate_synthetic_dataset(target, scale=scale, seed=seed)
    console.print(
        f"[green]Synthetic dataset written to {target}[/green] "
        f"({len(ds.aefi_truth)} AEFI rows, {len(ds.lots.lots)} lots)."
    )


@app.command()
def run(
    input_dir: Annotated[Path | None, typer.Option("--input", help="Directory with the raw files.")] = None,
    set_: Annotated[list[str] | None, typer.Option("--set", help="Config override key=value (repeatable).")] = None,
    no_release: Annotated[bool, typer.Option(help="Skip the public release build.")] = False,
) -> None:
    """Run the full pipeline (ingest → curate → analyse → release)."""
    from vamengoc.pipeline import run_pipeline
    from vamengoc.release.verify import verify_release

    project = Project(overrides=_parse_overrides(set_))
    src = input_dir or project.raw_dir
    outputs = run_pipeline(project, src, build_release=not no_release)
    console.print(f"[green]Run {outputs.run.run_id} finished.[/green] Manifest: {outputs.run.run_dir}")
    if outputs.release_dir is not None:
        rep = verify_release(project, outputs.release_dir)
        _report_verification(rep)
        if not rep.ok:
            raise typer.Exit(code=2)


@app.command()
def demo(
    scale: Annotated[float, typer.Option(help="Synthetic volume relative to the real data.")] = 0.3,
    seed: Annotated[int, typer.Option()] = 20260930,
    set_: Annotated[list[str] | None, typer.Option("--set", help="Config override key=value.")] = None,
) -> None:
    """Generate synthetic data and run the whole pipeline on it (release/synthetic)."""
    from vamengoc.pipeline import run_pipeline
    from vamengoc.release.verify import verify_release
    from vamengoc.synth import generate_synthetic_dataset

    project = Project(overrides=_parse_overrides(set_))
    generate_synthetic_dataset(project.synthetic_dir, scale=scale, seed=seed)
    outputs = run_pipeline(project, project.synthetic_dir, command="demo")
    assert outputs.release_dir is not None
    rep = verify_release(project, outputs.release_dir)
    _report_verification(rep)
    if not rep.ok:
        raise typer.Exit(code=2)


@app.command("schema-check")
def schema_check(
    input_dir: Annotated[Path | None, typer.Option("--input", help="Directory with the raw files.")] = None,
) -> None:
    """Map the headers of every input file to the schema registry (no analysis, no output files).

    Prints column titles only, never cell values. Checks the annual AEFI files, the event
    indicators each year's form carries, and the three sheets of the lot-release workbook.
    """
    from vamengoc.ingest.aefi import discover_aefi_files
    from vamengoc.ingest.lots import _find_sheet, find_lots_workbook
    from vamengoc.io.excel import list_sheets, read_sheet
    from vamengoc.io.schema_registry import SchemaError, detect_header_row, fields_from_schema

    project = Project()
    src = input_dir or project.raw_dir
    fields = fields_from_schema(project.aefi_schema["fields"])
    event_fields = [f.name for f in fields if f.name.startswith("ev_")]
    pii = {f.name for f in fields if f.kind == "pii_direct"}
    table = Table(title=f"AEFI files in {src}")
    for col in (
        "file",
        "sheet",
        "header row",
        "matched",
        "events on form",
        "identifiers (discarded)",
        "review",
        "unmatched",
        "missing required",
    ):
        table.add_column(col, no_wrap=col == "file", overflow="fold")
    problems = 0
    recorded: dict[str, set[str]] = {}
    files = discover_aefi_files(src, project.config.inputs.aefi_file_pattern)
    for _year, path in files:
        sheets = list_sheets(path)
        sheet = next((s for s in sheets if s.strip().upper() == project.config.inputs.aefi_preferred_sheet), sheets[0])
        grid = read_sheet(path, sheet)
        try:
            idx, m = detect_header_row(
                grid.rows,
                fields,
                max_rows=project.config.inputs.header_search_rows,
                min_matches=project.config.inputs.min_header_matches,
            )
        except SchemaError as exc:
            table.add_row(path.name, sheet, "-", "-", "-", "-", "-", "-", str(exc))
            problems += 1
            continue
        problems += bool(m.missing_required)
        mapped = set(m.field_to_column())
        recorded[path.name] = {e for e in event_fields if e in mapped}
        review = [f"{f['header']}→{f['field']}" for f in m.fuzzy]
        table.add_row(
            path.name,
            sheet,
            str(idx + 1),
            str(m.n_matched),
            f"{len(recorded[path.name])}/{len(event_fields)}",
            ", ".join(sorted(pii & mapped)) or "-",
            ", ".join(review) or "-",
            ", ".join(str(u["header"]) for u in m.unmatched) or "-",
            ", ".join(m.missing_required) or "-",
        )
    console.print(table)
    console.print(f"{len(files)} AEFI files checked, {problems} with problems.")

    # Change of form: events that are not on every file's form are analysed only where recorded.
    partial = [e for e in event_fields if recorded and 0 < sum(e in r for r in recorded.values()) < len(recorded)]
    if partial:
        console.print(
            f"[yellow]{len(partial)} event indicators are not on every year's form; each is analysed "
            "only in the files that record it (OPEN_QUESTIONS 11: equivalences between forms).[/yellow]"
        )
        for e in partial:
            on = [f for f, r in recorded.items() if e in r]
            console.print(f"  {e}: {', '.join(on)}")

    # Lot-release workbook (three sheets).
    lots_problems = 0
    try:
        lots_path = find_lots_workbook(src, project.config.inputs.lots_file_pattern)
    except (FileNotFoundError, SchemaError) as exc:
        console.print(f"[red]Lot-release workbook: {exc}[/red]")
        lots_problems += 1
    else:
        lt = Table(title=f"Lot-release workbook {lots_path.name}")
        for col in ("sheet", "header row", "matched", "review", "unmatched", "not found", "problem"):
            lt.add_column(col, overflow="fold")
        pats = project.config.inputs.sheet_patterns
        for key, sch_key in (("lots", "lots_sheet"), ("incidence", "incidence_sheet"), ("coverage", "coverage_sheet")):
            sch = project.lots_schema[sch_key]
            lfields = fields_from_schema(sch["fields"])
            try:
                sheet = _find_sheet(lots_path, pats[key])
                grid = read_sheet(lots_path, sheet)
                idx, m = detect_header_row(
                    grid.rows,
                    lfields,
                    max_rows=project.config.inputs.header_search_rows,
                    min_matches=int(sch["min_required_matches"]),
                )
            except SchemaError as exc:
                lt.add_row(key, "-", "-", "-", "-", "-", str(exc))
                lots_problems += 1
                continue
            problem = ", ".join(f"required: {f}" for f in m.missing_required)
            if key == "lots":
                quant = [f.name for f in lfields if f.type == "quantitative"]
                found = [q for q in quant if q in m.field_to_column()]
                minimum = int(sch.get("min_quality_attributes", 1))
                if len(found) < minimum:
                    problem = (problem + "; " if problem else "") + f"{len(found)} quality attributes (< {minimum})"
            lots_problems += bool(problem)
            lt.add_row(
                f"{key} ({sheet})",
                str(idx + 1),
                str(m.n_matched),
                ", ".join(f"{f['header']}→{f['field']}" for f in m.fuzzy) or "-",
                ", ".join(str(u["header"]) for u in m.unmatched) or "-",
                ", ".join(m.missing_optional) or "-",
                problem or "-",
            )
        console.print(lt)
        console.print(
            "Fields under 'not found' are optional: the analyses use the attributes present. If a "
            "header under 'unmatched' is one of them, add it as an alias in configs/schemas/lots.yaml."
        )
    if problems or lots_problems or not files:
        raise typer.Exit(code=1)


def _report_verification(rep: Any) -> None:
    if rep.ok:
        console.print(f"[green]Release verified: {rep.checked_files} files, no disclosure problems.[/green]")
    else:
        console.print(f"[red]Release verification FAILED ({len(rep.errors)} problems):[/red]")
        for e in rep.errors[:50]:
            console.print(f"  - {e}")


@release_app.command("verify")
def release_verify(origin: Annotated[str, typer.Argument(help="'public' or 'synthetic'.")] = "public") -> None:
    """Check a release for disclosure risks before it is committed."""
    from vamengoc.release.verify import verify_release

    project = Project()
    rep = verify_release(project, project.release_dir / origin)
    _report_verification(rep)
    if not rep.ok:
        raise typer.Exit(code=2)


@release_app.command("rebuild")
def release_rebuild(
    run_id: Annotated[str | None, typer.Option("--run", help="Run id (default: most recent snapshot).")] = None,
) -> None:
    """Rebuild tables, macros, figures and bundle from a stored results snapshot, then verify."""
    from vamengoc.pipeline import rebuild_release
    from vamengoc.release.verify import verify_release

    project = Project()
    try:
        root = rebuild_release(project, run_id)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Release rebuilt in {root}[/green]")
    rep = verify_release(project, root)
    _report_verification(rep)
    if not rep.ok:
        raise typer.Exit(code=2)


@release_app.command("summary")
def release_summary(origin: Annotated[str, typer.Argument()] = "synthetic") -> None:
    """Print the manifest summary of a release."""
    project = Project()
    manifest = json.loads((project.release_dir / origin / "manifest.json").read_text(encoding="utf-8"))
    keep = {
        k: manifest[k]
        for k in (
            "data_origin",
            "generated_utc",
            "run_id",
            "code_version",
            "git_commit",
            "n_tables",
            "n_figures",
            "sdc_log",
        )
        if k in manifest
    }
    console.print_json(json.dumps(keep, default=str))


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address (keep 127.0.0.1: local use only).")] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8765,
) -> None:
    """Start the local lab API used by the web application (runs the pipeline locally)."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - optional extra
        console.print("[red]Install the 'app' extra: uv sync --extra app[/red]")
        raise typer.Exit(code=1) from exc
    if host not in {"127.0.0.1", "localhost", "::1"}:
        console.print("[yellow]Warning: binding to a non-loopback address exposes the local lab API.[/yellow]")
    token = os.environ.get("VAMENGOC_LAB_TOKEN") or secrets.token_urlsafe(24)
    os.environ["VAMENGOC_LAB_TOKEN"] = token
    console.print(f"[green]Local lab API on http://{host}:{port}[/green]")
    console.print(f"Session token (paste it in the web app, 'Laboratorio local'): [bold]{token}[/bold]")
    from vamengoc.api.server import create_app

    uvicorn.run(create_app(token=token), host=host, port=port, log_level="info")  # pragma: no cover


def main() -> None:  # pragma: no cover - console entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
