# corrections

Manual corrections to the Chicago crash data for the crash-mapping project.
Today that is one thing: the **redactions** blocklist — crash, person, and
vehicle records that should be excluded from the site (drive-by shootings
filed as crashes, duplicated people/vehicles, and so on).

- `seeds/redactions.yaml` — the source of truth, hand-edited.
- `redactions.csv` — built from the YAML and committed here. server-chicagocrashes
  loads it straight from GitHub with `make db-update-redactions`
  (`https://raw.githubusercontent.com/crashstop/corrections/refs/heads/main/redactions.csv`).

## Usage

```sh
make            # seeds/redactions.yaml -> redactions.csv (validates ids against db.sqlite)
make check      # validate only, don't rewrite the CSV
make test       # pytest
```

Then commit and push `redactions.csv`; on the server side run
`make db-update-redactions` (or `make prod-update-redactions`).

`db.sqlite` is a symlink to server-chicagocrashes' `data/db.sqlite`; the build
checks every id in the YAML against its `raw_crashes` / `raw_people` /
`raw_vehicles` tables and fails on any miss. If the symlink is dangling the
check is skipped with a warning.

Requires Python 3.14+ and pyyaml (`pip install -e '.[test]'`).

## YAML format

```yaml
- crash_record_id: <128-hex crash id>
  ignore_crash_completely: true
  notes: |
    why, with a link if there is one

- crash_record_id: <128-hex crash id>
  ignore_crash_completely: false
  notes: "driver dupe"
  ignore_person_ids: [O870676]
  ignore_vehicle_ids: [826028]
```

## CSV format

`crash_record_id, record_id, record_type, notes`. One row per redacted
record; `record_type` is `crash`, `person`, or `vehicle`. For crash rows
`record_id` equals `crash_record_id`. Rows are sorted so a no-op rebuild is a
no-op diff.
