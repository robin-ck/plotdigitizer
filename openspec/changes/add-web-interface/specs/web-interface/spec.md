# Delta: web-interface

## ADDED Requirements

### Requirement: Anonymous sessions
The system SHALL create a private session with an unguessable link when a PDF is uploaded, and SHALL delete the whole session (PDF, card, points, CSVs, logs) after the retention period (default 7 days).

#### Scenario: Upload creates a session
- **WHEN** a user uploads a valid PDF with a citekey
- **THEN** the system returns a session link, and the upload page states the expiry date and that the CSV must be downloaded before then

#### Scenario: Expired session
- **WHEN** a session is older than the retention period
- **THEN** its directory is deleted and its link returns "expired"

#### Scenario: Sessions are isolated
- **WHEN** a request uses a token other than the session's own
- **THEN** none of that session's data is returned

### Requirement: Upload limits
The system MUST reject files that are not PDFs, exceed the size or page limit, or arrive when the disk cap is reached, with a clear message.

#### Scenario: Oversized upload
- **WHEN** a user uploads a file over the size limit
- **THEN** the upload is rejected and nothing is stored

### Requirement: Figure selection
The system SHALL list the figures found in the PDF with page number, thumbnail and kind, and SHALL mark raster and non-plot figures as not supported.

#### Scenario: Pick a vector figure
- **WHEN** the user picks a supported figure
- **THEN** the set-up screen opens on that figure's page

### Requirement: Figure set-up
The system SHALL let the user draw panel, legend and inset boxes on the page image, SHALL show the tick positions detected inside a drawn panel box, and SHALL build a Figure Card from the user's boxes, tick values, units, scale options and series names that validates against the Figure Card schema.

#### Scenario: Ticks detected for a drawn box
- **WHEN** the user draws a panel box around a plot
- **THEN** the detected x and y tick positions are marked on the page and the form shows how many ticks were found per axis

#### Scenario: Tick count mismatch
- **WHEN** the number of entered tick values differs from the detected ticks
- **THEN** the form flags the axis and extraction is not started

#### Scenario: Extract
- **WHEN** the user presses "Extract points" with a complete card
- **THEN** the card is saved, extraction runs, and the review screen opens

### Requirement: Side-by-side review
The system SHALL show the original plot (read-only) next to the detected points re-plotted from their values on the same axes, with shared zoom and pan, and a crosshair on both views at the selected point.

#### Scenario: Select a point
- **WHEN** the user selects a point in either view or in the points table
- **THEN** both views show a crosshair at that position and the table row is highlighted

### Requirement: Point editing
The system SHALL let the user move, add (with a chosen series), delete and undo points, and edit values in the table. All value and position conversions SHALL be done server-side with the panel's calibration, and each change SHALL be logged with old and new position and value.

#### Scenario: Move a point
- **WHEN** the user drags a point to a new position
- **THEN** the server recomputes its values, logs `manual_move`, reruns the checks and updates the CSV

#### Scenario: Edit a value in the table
- **WHEN** the user types a new value for a point
- **THEN** the server converts it to a position, moves the point in both views and logs the change

### Requirement: Re-extraction after edits
The system SHALL warn before re-extraction discards manual edits, and SHALL keep the log of earlier runs.

#### Scenario: Re-extract with edits
- **WHEN** the user re-runs extraction on a figure with manual edits and confirms the warning
- **THEN** the edits are discarded, extraction reruns, and `log.jsonl` contains both runs separated by a `run_start` event

### Requirement: Validation
The system SHALL let the user mark a figure validated once every panel has been opened in review. If error-level checks fail, the system MUST require a typed reason per failing check. Validation SHALL set every point's confidence to "manuell geprüft" and record `validated`, timestamp and reasons in `state.json` and the log. Any later edit SHALL clear the validated state.

#### Scenario: Validate with a failing check
- **WHEN** the user marks a figure validated while the marker-count check fails
- **THEN** a dialog asks for a reason, and validation is recorded with that reason

#### Scenario: Edit after validation
- **WHEN** a point of a validated figure is moved
- **THEN** the figure is no longer marked validated

### Requirement: CSV download
The system SHALL offer the long-format CSV and the spreadsheet variant for each figure and for all figures in the session, in the same columns as the CLI output.

#### Scenario: Download
- **WHEN** the user presses "Download CSV"
- **THEN** the file matches what `plotdigitizer digitize` would produce for the same card and edits

### Requirement: Job limits
The system MUST run extraction and rendering jobs with a hard timeout and a cap on concurrent jobs, and MUST rate-limit uploads and jobs per client IP.

#### Scenario: Stuck job
- **WHEN** a job exceeds the timeout
- **THEN** it is killed and the user sees an error with a retry option

#### Scenario: Too many requests
- **WHEN** a client exceeds the rate limit
- **THEN** the server answers 429 and stores nothing
