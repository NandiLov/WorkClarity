-- WorkClarity synthetic dataset schema for BigQuery. Keys are informational (NOT ENFORCED) but help joins and the query planner.
-- Create the dataset first: bq mk --dataset workclarity_dev

CREATE OR REPLACE TABLE workclarity_dev.workers (
  worker_id STRING NOT NULL,
  worker_name STRING,
  home_area STRING,
  transport_mode STRING,
  PRIMARY KEY (worker_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE workclarity_dev.employers (
  employer_id STRING NOT NULL,
  employer_name STRING,
  industry STRING,
  default_rate FLOAT64,
  PRIMARY KEY (employer_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE workclarity_dev.locations (
  location_id STRING NOT NULL,
  employer_id STRING,
  location_name STRING,
  area STRING,
  PRIMARY KEY (location_id) NOT ENFORCED,
  CONSTRAINT fk_locations_employer_id FOREIGN KEY (employer_id) REFERENCES workclarity_dev.employers(employer_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE workclarity_dev.case_types (
  case_type_id STRING NOT NULL,
  case_type STRING,
  description STRING,
  PRIMARY KEY (case_type_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE workclarity_dev.flag_types (
  flag_type_id STRING NOT NULL,
  flag_name STRING,
  severity STRING,
  worker_message STRING,
  PRIMARY KEY (flag_type_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE workclarity_dev.error_types (
  error_type_id STRING NOT NULL,
  error_type STRING,
  severity STRING,
  description STRING,
  flag_type_id STRING,
  PRIMARY KEY (error_type_id) NOT ENFORCED,
  CONSTRAINT fk_error_types_flag_type_id FOREIGN KEY (flag_type_id) REFERENCES workclarity_dev.flag_types(flag_type_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE workclarity_dev.pay_rules (
  rule_id STRING NOT NULL,
  rule_name STRING,
  value STRING,
  description STRING,
  PRIMARY KEY (rule_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE workclarity_dev.schedules (
  schedule_id STRING NOT NULL,
  worker_id STRING,
  case_type_id STRING,
  source_format STRING,
  file_name STRING,
  pay_week_start DATE,
  schedule_version INT64,
  description STRING,
  uploaded_at TIMESTAMP,
  PRIMARY KEY (schedule_id) NOT ENFORCED,
  CONSTRAINT fk_schedules_worker_id FOREIGN KEY (worker_id) REFERENCES workclarity_dev.workers(worker_id) NOT ENFORCED,
  CONSTRAINT fk_schedules_case_type_id FOREIGN KEY (case_type_id) REFERENCES workclarity_dev.case_types(case_type_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE workclarity_dev.truth_shifts (
  shift_id STRING NOT NULL,
  schedule_id STRING,
  line_no INT64,
  worker_id STRING,
  employer_id STRING,
  location_id STRING,
  department STRING,
  shift_date DATE,
  start_time STRING,
  end_time STRING,
  ends_next_day BOOL,
  break_minutes INT64,
  break_paid BOOL,
  hourly_rate FLOAT64,
  currency STRING,
  pay_type STRING,
  shift_status STRING,
  counts_toward_earnings BOOL,
  travel_minutes_to_next_shift INT64,
  paid_hours FLOAT64,
  gross_earnings FLOAT64,
  verified_by STRING,
  verified_at DATE,
  PRIMARY KEY (shift_id) NOT ENFORCED,
  CONSTRAINT fk_truth_shifts_schedule_id FOREIGN KEY (schedule_id) REFERENCES workclarity_dev.schedules(schedule_id) NOT ENFORCED,
  CONSTRAINT fk_truth_shifts_worker_id FOREIGN KEY (worker_id) REFERENCES workclarity_dev.workers(worker_id) NOT ENFORCED,
  CONSTRAINT fk_truth_shifts_employer_id FOREIGN KEY (employer_id) REFERENCES workclarity_dev.employers(employer_id) NOT ENFORCED,
  CONSTRAINT fk_truth_shifts_location_id FOREIGN KEY (location_id) REFERENCES workclarity_dev.locations(location_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE workclarity_dev.raw_shifts (
  raw_id STRING NOT NULL,
  schedule_id STRING,
  line_no INT64,
  worker_id STRING,
  shift_date STRING,
  start_time STRING,
  end_time STRING,
  break_minutes INT64,
  hourly_rate FLOAT64,
  location_text STRING,
  employer_name STRING,
  department STRING,
  currency STRING,
  stated_hours FLOAT64,
  shift_status STRING,
  source_format STRING,
  file_name STRING,
  source_line STRING,
  extraction_method STRING,
  extraction_version STRING,
  extraction_confidence FLOAT64,
  confirmation_status STRING,
  extracted_at TIMESTAMP,
  PRIMARY KEY (raw_id) NOT ENFORCED,
  CONSTRAINT fk_raw_shifts_schedule_id FOREIGN KEY (schedule_id) REFERENCES workclarity_dev.schedules(schedule_id) NOT ENFORCED,
  CONSTRAINT fk_raw_shifts_worker_id FOREIGN KEY (worker_id) REFERENCES workclarity_dev.workers(worker_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE workclarity_dev.raw_truth_map (
  raw_id STRING NOT NULL,
  shift_id STRING,
  PRIMARY KEY (raw_id) NOT ENFORCED,
  CONSTRAINT fk_raw_truth_map_raw_id FOREIGN KEY (raw_id) REFERENCES workclarity_dev.raw_shifts(raw_id) NOT ENFORCED,
  CONSTRAINT fk_raw_truth_map_shift_id FOREIGN KEY (shift_id) REFERENCES workclarity_dev.truth_shifts(shift_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE workclarity_dev.planted_errors (
  error_id STRING NOT NULL,
  raw_id STRING,
  error_type_id STRING,
  PRIMARY KEY (error_id) NOT ENFORCED,
  CONSTRAINT fk_planted_errors_raw_id FOREIGN KEY (raw_id) REFERENCES workclarity_dev.raw_shifts(raw_id) NOT ENFORCED,
  CONSTRAINT fk_planted_errors_error_type_id FOREIGN KEY (error_type_id) REFERENCES workclarity_dev.error_types(error_type_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE workclarity_dev.expected_weekly_earnings (
  weekly_id STRING NOT NULL,
  worker_id STRING,
  schedule_id STRING,
  pay_week_start DATE,
  currency STRING,
  shifts INT64,
  incomplete_shifts INT64,
  cancelled_shifts INT64,
  paid_hours FLOAT64,
  regular_hours FLOAT64,
  overtime_hours FLOAT64,
  expected_gross_mvp FLOAT64,
  expected_gross_with_overtime FLOAT64,
  PRIMARY KEY (weekly_id) NOT ENFORCED,
  CONSTRAINT fk_expected_weekly_earnings_worker_id FOREIGN KEY (worker_id) REFERENCES workclarity_dev.workers(worker_id) NOT ENFORCED,
  CONSTRAINT fk_expected_weekly_earnings_schedule_id FOREIGN KEY (schedule_id) REFERENCES workclarity_dev.schedules(schedule_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE workclarity_dev.expected_conflicts (
  conflict_id STRING NOT NULL,
  worker_id STRING,
  shift_a_id STRING,
  shift_b_id STRING,
  conflict_type STRING,
  gap_minutes INT64,
  PRIMARY KEY (conflict_id) NOT ENFORCED,
  CONSTRAINT fk_expected_conflicts_worker_id FOREIGN KEY (worker_id) REFERENCES workclarity_dev.workers(worker_id) NOT ENFORCED,
  CONSTRAINT fk_expected_conflicts_shift_a_id FOREIGN KEY (shift_a_id) REFERENCES workclarity_dev.truth_shifts(shift_id) NOT ENFORCED,
  CONSTRAINT fk_expected_conflicts_shift_b_id FOREIGN KEY (shift_b_id) REFERENCES workclarity_dev.truth_shifts(shift_id) NOT ENFORCED
);

CREATE OR REPLACE TABLE workclarity_dev.shift_details (
  shift_id STRING NOT NULL,
  schedule_id STRING,
  worker_id STRING,
  employer_id STRING,
  location_id STRING,
  case_type_id STRING,
  worker_name STRING,
  employer_name STRING,
  location_name STRING,
  department STRING,
  shift_date DATE,
  start_time STRING,
  end_time STRING,
  ends_next_day BOOL,
  break_minutes INT64,
  hourly_rate FLOAT64,
  currency STRING,
  pay_type STRING,
  shift_status STRING,
  counts_toward_earnings BOOL,
  paid_hours FLOAT64,
  gross_earnings FLOAT64,
  case_type STRING,
  PRIMARY KEY (shift_id) NOT ENFORCED,
  CONSTRAINT fk_shift_details_shift_id FOREIGN KEY (shift_id) REFERENCES workclarity_dev.truth_shifts(shift_id) NOT ENFORCED,
  CONSTRAINT fk_shift_details_schedule_id FOREIGN KEY (schedule_id) REFERENCES workclarity_dev.schedules(schedule_id) NOT ENFORCED,
  CONSTRAINT fk_shift_details_worker_id FOREIGN KEY (worker_id) REFERENCES workclarity_dev.workers(worker_id) NOT ENFORCED,
  CONSTRAINT fk_shift_details_employer_id FOREIGN KEY (employer_id) REFERENCES workclarity_dev.employers(employer_id) NOT ENFORCED,
  CONSTRAINT fk_shift_details_location_id FOREIGN KEY (location_id) REFERENCES workclarity_dev.locations(location_id) NOT ENFORCED,
  CONSTRAINT fk_shift_details_case_type_id FOREIGN KEY (case_type_id) REFERENCES workclarity_dev.case_types(case_type_id) NOT ENFORCED
);
