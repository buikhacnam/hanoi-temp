CREATE TABLE weather_daily (
  date TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('historical','forecast')),
  month_day TEXT NOT NULL,
  mean REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  model TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (date, kind),
  CHECK (low <= mean AND mean <= high)
);
CREATE INDEX weather_calendar_day ON weather_daily(kind, month_day, date);
