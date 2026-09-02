# MethodAtom Parameter UI Contract

Last updated: 2026-09-02

This document defines how MethodAtom templates control parameter editing in the WebUI. The goal is to keep parameter behavior owned by the atom registry, so adding or changing atoms does not require React component changes.

## Contract Summary

`MethodAtomTemplate` may declare two UI-facing metadata fields:

| Field | Type | Purpose |
|---|---|---|
| `parameter_options` | `dict[str, list[Any]]` | Fixed candidate values for parameters. The WebUI renders these as select menus. |
| `parameter_specs` | `dict[str, dict[str, Any]]` | Per-parameter UI/control metadata such as type, control, range, grouping, placeholder, and description. |

The `/api/atom-templates` endpoint returns both fields for each template. When a template is dropped onto the canvas, the WebUI stores these fields in the atom metadata so the created atom carries its own parameter UI contract.

Older template records may still expose `NodeTemplate`-era names through the
compatibility layer, but new templates and docs should use `MethodAtomTemplate`.

## Parameter Options

Use `parameter_options` when a parameter should be selected from a fixed set.

```python
MethodAtomTemplate(
    template_id="bandpass_filter",
    default_config={"method": "fir", "fir_design": "firwin"},
    parameter_options={
        "method": ["fir", "iir"],
        "fir_design": ["firwin", "firwin2"],
    },
)
```

The WebUI preserves the option value type. Numeric options remain numeric when saved.

## Parameter Specs

Use `parameter_specs` to control how a parameter is presented.

```python
MethodAtomTemplate(
    template_id="bandpass_filter",
    default_config={"l_freq": 0.01, "h_freq": 0.2, "method": "fir"},
    parameter_options={"method": ["fir", "iir"]},
    parameter_specs={
        "l_freq": {"type": "number", "control": "number", "minimum": 0},
        "h_freq": {"type": "number", "control": "number", "minimum": 0},
        "method": {"type": "text", "control": "select"},
    },
)
```

Supported spec keys:

| Key | Type | Behavior |
|---|---|---|
| `type` | `text`, `number`, `number-list`, `boolean` | Parameter value type used by the editor and bulk import/export. |
| `control` | `text`, `number`, `select`, `checkbox`, `path` | Preferred WebUI control. |
| `description` | `string` | Helper text displayed below the field. |
| `placeholder` | `string` | Input placeholder. |
| `advanced` | `boolean` | Moves the parameter into Advanced Parameters when true. |
| `minimum` / `maximum` | `number` | Numeric range bounds. |
| `min` / `max` | `number` | Alternate numeric range bounds. |
| `range` | `[number, number]` or object | Numeric range displayed by the editor. |
| `enum` | `list[Any]` | Additional fixed values, treated like `parameter_options`. |
| `source` | `string` | Optional provenance label for the parameter row. |

## Built-In Inference

The handwritten template registry attaches common specs and options in `fnirs_flow.registry.node_templates.attach_common_parameter_options`. This is registry-layer behavior, not WebUI behavior. It exists to keep common atom parameters consistent while still allowing each atom to override fields explicitly.

Examples:

| Parameter | Registry behavior |
|---|---|
| `bids_dir`, `path`, `reference_dir` | `control: "path"` |
| `design_type`, `hrf_model`, `kernel`, `format` | Fixed options and `control: "select"` |
| `l_freq`, `h_freq` | `type: "number"`, `minimum: 0` |
| `alpha`, `dropout`, `*_threshold` | `type: "number"`, `minimum: 0`, `maximum: 1` |

Literature-derived templates are also passed through the same registry-layer attachment before `/api/atom-templates` returns them.

## WebUI Responsibilities

The WebUI should:

- Render controls from `parameter_specs` and `parameter_options`.
- Preserve option value types when saving.
- Use legacy fallbacks only for old flows that lack parameter metadata.
- Avoid hardcoding atom-specific parameter names or scientific choices in React components.

The WebUI should not:

- Decide scientific parameter candidates.
- Infer atom-specific dropdown contents.
- Encode new atom behavior in component conditionals.

## Adding A New Atom

When adding a MethodAtom, keep the UI contract beside the atom definition:

1. Put default values in `default_config`.
2. Put fixed choices in `parameter_options`.
3. Put control/range/grouping/help text in `parameter_specs`.
4. Add or update tests if the parameter UI contract is important for that atom.
