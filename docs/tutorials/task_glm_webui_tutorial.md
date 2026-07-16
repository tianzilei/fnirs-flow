# Task GLM WebUI Tutorial

This tutorial walks through a complete fnirs-flow WebUI analysis path for a task-based GLM workflow. It uses screenshots captured from the public WebUI test run and is intended for README links, onboarding, teaching, and reviewer-facing demonstrations.

The tutorial path is:

1. Create a project.
2. Load and save a Task GLM Flow.
3. Validate and compile the Flow.
4. Bind data and inspect participant metadata.
5. Run a dry run.
6. Execute the analysis.
7. Review artifacts, QC, channel, ROI, and group results.
8. Export a reproducibility package.
9. Check system diagnostics.

## 1. Create a Project

Open the WebUI and start from the Projects page.

![Projects page](assets/task-glm-webui/01-projects-start.png)

Click **New Project** and enter a project name. A clear project name is helpful because the same project will store the Flow, validation state, data binding, run records, and export history.

![Create project form](assets/task-glm-webui/02-create-project-form.png)

After creation, the project opens in the Flow workspace. A new project may start with an empty canvas and a MethodAtom library on the left.

![Empty Flow project](assets/task-glm-webui/03-empty-flow-project.png)

## 2. Load and Save the Task GLM Flow

Load or apply a Task GLM Flow. The Flow canvas should show the analysis chain from data inputs through preprocessing, design matrix construction, GLM, contrast estimation, QC, and outputs.

![Loaded GLM Flow](assets/task-glm-webui/04-loaded-glm-flow.png)

Save the Flow before moving to validation. Saving records the editable project state, not just a static picture of the canvas.

## 3. Validate and Compile

Open the validation dashboard. Validation checks the graph, ports, adapter compatibility, parameters, readiness, and fatal risks before execution is allowed.

![Validation dashboard](assets/task-glm-webui/07-checks-validation-dashboard.png)

After validation, compile the Flow. Compilation turns the visual Flow into an executable plan, execution DAG, and manifest set.

![Compile results](assets/task-glm-webui/09-compile-results.png)

Use the compile summary to confirm the selected plan, DAG, hash, atom count, and output files. Dry run and execution should be based on the compiled plan rather than the raw canvas alone.

## 4. Bind Data and Participant Metadata

Open the Data Workspace. Select the dataset that will be used for execution.

![Data Workspace](assets/task-glm-webui/10-data-workspace-before-discovery.png)

Run dataset discovery. A successful discovery result confirms that fnirs-flow can locate and describe the data source.

![Data discovery success](assets/task-glm-webui/14-data-discovery-success.png)

Import or configure the participant table. The Join Preview helps confirm whether participant metadata matches the discovered data.

![Participant Join Preview](assets/task-glm-webui/16-participant-join-preview.png)

If the matched count is unexpected, fix the dataset root, participant labels, or participant table before moving to execution.

## 5. Dry Run

Open the Runs page and start with **Dry Run**. Dry run enumerates the subject/session/run units and checks the execution plan without running the full analysis.

![Dry Run results](assets/task-glm-webui/18-dry-run-results.png)

Use this step to confirm the batch size and intended run list. It is the best place to catch scope mistakes before launching a longer computation.

## 6. Fix Validation Issues if Needed

If validation reports fatal or invalid states, return to the Flow and parameter panels, fix the issue, and validate again. Continue only after the dashboard reports a valid Flow.

![Validation valid](assets/task-glm-webui/26-fixed-validation-valid.png)

## 7. Execute the Analysis

Once the Flow is valid and the data binding is ready, execute the run. The Run Monitor records status and timing at the run level.

![Execution complete](assets/task-glm-webui/29-third-execute-final.png)

Completed, failed, and running states remain visible for review and troubleshooting.

## 8. Review Results

Open the Results Workspace and start with artifacts. Artifacts are the concrete outputs produced by the execution chain.

![Artifacts](assets/task-glm-webui/30-results-artifacts.png)

Review QC outputs next. QC tables help determine whether channels and runs are suitable for interpretation.

![QC results](assets/task-glm-webui/31-results-qc.png)

Then review channel-level statistics.

![Channel results](assets/task-glm-webui/32-results-channel.png)

Review ROI-level results for region-level summaries.

![ROI results](assets/task-glm-webui/33-results-roi.png)

Finally, inspect group-level results.

![Group results](assets/task-glm-webui/34-results-group.png)

## 9. Export a Package

Open the Export page and choose the package profile that matches the handoff goal.

![Export page](assets/task-glm-webui/35-export-before.png)

Typical profile choices:

| Profile | Use case |
|---|---|
| `submission_package` | Journal submission and supplementary material |
| `reviewer_package` | Peer-review inspection with additional provenance and failure manifests |
| `reproducibility_package` | Cross-machine rerun after relinking data |

Exported packages do not include raw data by default. They include the analysis plan, compiled outputs, manifests, validation reports, and relink instructions according to the selected profile.

## 10. Check System Diagnostics

If a run fails or a backend appears unavailable, open System Diagnostics. This page summarizes API connectivity, backend availability, environment state, and a health response.

![System diagnostics](assets/task-glm-webui/37-system-diagnostics.png)

System Diagnostics is also useful when preparing a demo because it confirms that the backend and WebUI are communicating before the tutorial begins.

## Troubleshooting Notes

| Symptom | Suggested check |
|---|---|
| Dataset discovery finds no files | Confirm the dataset root and BIDS/SNIRF structure. |
| Participant Join Preview shows unmatched rows | Check participant labels and `participants.tsv` values. |
| Execute is disabled | Re-run validation and compilation; fatal validation risks block execution. |
| Export is disabled or returns no compiled plan | Compile the Flow first and confirm the plan exists. |
| Backend execution fails | Open System Diagnostics and check MNE-NIRS or Cedalion availability. |

## Teaching Script

For a short demo, use this pacing:

1. 10 seconds: create project and show the Flow canvas.
2. 30 seconds: validate, compile, discover data, and inspect participant matching.
3. 30 seconds: dry run, execute, and show the Run Monitor.
4. 30 seconds: switch through artifacts, QC, channel, ROI, and group results.
5. 10 seconds: show package export and System Diagnostics.

The main point to emphasize is that fnirs-flow turns fNIRS analysis into a validated, executable, inspectable, and portable MethodAtom Flow.
