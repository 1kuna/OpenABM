from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps" / "web" / "src" / "App.tsx"
STYLES = ROOT / "apps" / "web" / "src" / "styles.css"


def read_app() -> str:
    return APP.read_text()


def test_work_surfaces_register_palette_commands_and_bulk_selection() -> None:
    source = read_app()

    assert "const [viewCommands, setViewCommands]" in source
    assert "onCommandsChange={setViewCommands}" in source

    for token in [
        "selectedTraceIds",
        "toggleAllVisibleTraces",
        "investigations:dataset:add-selected",
        "investigations:dataset:add-current",
        "investigations:similar",
        "selectedTaskIds",
        "toggleAllVisibleTasks",
        "reviews:accept-selected",
        "reviews:evidence-selected",
        "reviews:reject-selected",
    ]:
        assert token in source


def test_work_refresh_and_settings_controls_follow_ux_direction() -> None:
    source = read_app()

    assert 'const WORK_VIEWS = new Set<ViewKey>(["now", "investigations", "reviews"])' in source
    assert '!WORK_VIEWS.has(activeView) ? (' in source
    assert '<div className="connectionBox">' not in source
    assert "<h4>Local connection</h4>" in source


def test_bulk_selection_styles_are_shared_across_work_lists() -> None:
    styles = STYLES.read_text()

    for token in [
        ".listBulkBar",
        ".reviewRowItem",
        ".rowSelect input",
        ".tableSelectCell input",
        ".selectColumn input",
    ]:
        assert token in styles
