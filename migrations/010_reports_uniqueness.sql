DELETE FROM reports
WHERE rowid NOT IN (
  SELECT MAX(rowid)
  FROM reports
  GROUP BY user_id, report_date, report_type
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_user_date_type_unique
  ON reports (user_id, report_date, report_type);
