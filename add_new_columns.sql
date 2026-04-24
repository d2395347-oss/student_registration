-- Run this in Railway Query tab or MySQL Workbench
USE railway;

-- Add registration number column
ALTER TABLE students ADD COLUMN IF NOT EXISTS reg_no VARCHAR(20) UNIQUE AFTER id;

-- Add photo column
ALTER TABLE students ADD COLUMN IF NOT EXISTS photo VARCHAR(255) AFTER email;

-- Verify
DESCRIBE students;
