# Using the radar with MySQL

The pipeline stores data in SQLite automatically. To query it in MySQL / MySQL Workbench:

**1. Dump the tables** (in the project folder, Terminal):
```bash
export PYTHONPATH=src
python3 -m radar.pipeline export-tables
```
This writes `data/exports/tables/jobs.csv` and `job_skills.csv`.

**2. Allow local file loading** (one time):
- In MySQL Workbench, run: `SET GLOBAL local_infile = 1;`
- Edit your connection → **Advanced** tab → in **Others**, add `OPT_LOCAL_INFILE=1` → reconnect

**3. Create the tables:** open and run `sql/mysql/schema.sql`

**4. Load the data:** open `sql/mysql/load_data.sql`, replace `/PATH/TO` with your project folder's full path (run `pwd` in Terminal to see it), then run it. The last line should show the row counts.

**5. Analyze:** run the queries in `sql/mysql/analysis.sql`, or write your own. Query 7 is a window-function example (`RANK() OVER (PARTITION BY ...)`), a common interview topic.

Re-run steps 1, 3 and 4 whenever you fetch new data.
