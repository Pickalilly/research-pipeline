"""Research pipeline web app."""

import asyncio
import re
import sys
from pathlib import Path

# Load .env if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Load config
if sys.version_info >= (3, 11):
    import tomllib
    _open_toml = lambda p: open(p, "rb")
else:
    import tomli as tomllib
    _open_toml = lambda p: open(p, "rb")

_CONFIG_PATH = Path(__file__).parent / "config.toml"
with open(_CONFIG_PATH, "rb") as _f:
    _CONFIG = tomllib.load(_f)

AVAILABLE_MODELS: list[str] = _CONFIG["models"]["available"]
DEFAULTS: dict = _CONFIG["defaults"]

from nicegui import app, ui
from pipeline import run_pipeline


def slugify(topic: str) -> str:
    """Convert topic to a filesystem-safe slug."""
    slug = topic.lower()
    slug = slug.replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "unnamed"


def build_ui() -> None:
    """Construct the NiceGUI page."""

    # ── State ────────────────────────────────────────────────────────────────
    state = {
        "topic_dir": None,
        "log_buffer": [],
    }

    # ── Layout ───────────────────────────────────────────────────────────────
    with ui.column().classes("w-full max-w-4xl mx-auto q-pa-md gap-4"):

        ui.label("Research Pipeline").classes("text-2xl font-bold")

        # Topic input
        topic_input = ui.input(
            placeholder="Enter a research topic..."
        ).classes("w-full")

        # Model selectors
        with ui.grid(columns=2).classes("w-full gap-4"):
            orchestrator_select = ui.select(
                label="Orchestrator model",
                options=AVAILABLE_MODELS,
                value=DEFAULTS["orchestrator"],
            ).classes("w-full")

            researcher_select = ui.select(
                label="Web researcher model",
                options=AVAILABLE_MODELS,
                value=DEFAULTS["web_researcher"],
            ).classes("w-full")

            fact_checker_select = ui.select(
                label="Fact checker model",
                options=AVAILABLE_MODELS,
                value=DEFAULTS["fact_checker"],
            ).classes("w-full")

            red_team_select = ui.select(
                label="Red team model",
                options=AVAILABLE_MODELS,
                value=DEFAULTS["red_team"],
            ).classes("w-full")

        # Run button
        run_btn = ui.button("Run Pipeline").classes("w-full")

        # Live log area
        log_area = ui.textarea(label="Live log").classes("w-full font-mono text-sm")
        log_area.props("rows=20 readonly outlined")

        # Download button (hidden until pipeline completes)
        download_btn = ui.button("Download report.md").classes("w-full")
        download_btn.visible = False

    # ── Helpers ──────────────────────────────────────────────────────────────

    def append_log(text: str) -> None:
        """Append text to the log area."""
        current = log_area.value or ""
        log_area.set_value(current + text)
        # Scroll to bottom via JS
        ui.run_javascript(
            "var el = document.querySelector('.q-textarea textarea');"
            "if(el){ el.scrollTop = el.scrollHeight; }"
        )

    def on_token(token: str) -> None:
        """Called from the pipeline for each streaming token."""
        append_log(token)

    async def on_run_click() -> None:
        topic = topic_input.value.strip()
        if not topic:
            ui.notify("Please enter a research topic.", type="warning")
            return

        # Prepare directories
        slug = slugify(topic)
        base_dir = Path(__file__).parent / "topics" / slug
        base_dir.mkdir(parents=True, exist_ok=True)
        state["topic_dir"] = base_dir

        # Reset UI
        run_btn.disable()
        download_btn.visible = False
        log_area.set_value("")
        append_log(f"Starting pipeline for: {topic}\n\n")

        models = {
            "orchestrator": orchestrator_select.value,
            "web_researcher": researcher_select.value,
            "fact_checker": fact_checker_select.value,
            "red_team": red_team_select.value,
        }

        async def pipeline_task() -> None:
            try:
                await run_pipeline(
                    topic=topic,
                    topic_dir=base_dir,
                    models=models,
                    num_researchers=3,
                    on_token=on_token,
                )
                append_log("\n\nPipeline complete.")
                report_path = base_dir / "report.md"
                if report_path.exists():
                    download_btn.visible = True
            except Exception as exc:
                append_log(f"\n\nError: {exc}")
            finally:
                run_btn.enable()

        asyncio.create_task(pipeline_task())

    run_btn.on_click(on_run_click)

    # ── Download handler ─────────────────────────────────────────────────────

    @ui.refreshable
    def _noop() -> None:
        pass

    def on_download_click() -> None:
        topic_dir = state.get("topic_dir")
        if topic_dir is None:
            return
        report_path = topic_dir / "report.md"
        if report_path.exists():
            ui.download(str(report_path), filename="report.md")
        else:
            ui.notify("Report not found.", type="negative")

    download_btn.on_click(on_download_click)


@ui.page("/")
def index() -> None:
    build_ui()


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(port=8080, title="Research Pipeline")
