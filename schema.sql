-- ================================================
-- STUDENT REGISTRATION DATABASE SCHEMA
-- Run this once to set up your MySQL database
-- ================================================

CREATE DATABASE IF NOT EXISTS school_db;
USE school_db;

-- ===== STUDENTS TABLE =====
CREATE TABLE IF NOT EXISTS students (
    id                       INT AUTO_INCREMENT PRIMARY KEY,
    name                     VARCHAR(100)  NOT NULL,
    father_name              VARCHAR(100)  NOT NULL,
    date_of_birth            VARCHAR(20)   NOT NULL,
    address                  TEXT,
    father_occupation        VARCHAR(100),
    academic_year            VARCHAR(20),
    previous_institution_name VARCHAR(200),
    class_applied            VARCHAR(20)   NOT NULL,
    category                 VARCHAR(20)   NOT NULL,
    gender                   VARCHAR(10),
    phone_no                 VARCHAR(15)   NOT NULL,
    aadhaar_no               VARCHAR(64)   NOT NULL,   -- SHA-256 hash stored, not raw
    pan_no                   VARCHAR(20)   NOT NULL,
    special_child            VARCHAR(5)    DEFAULT 'no',
    extra_activity           VARCHAR(5)    DEFAULT 'no',
    achievement              VARCHAR(5)    DEFAULT 'no',
    hobbies                  VARCHAR(200),
    sports                   VARCHAR(200),
    special_file             VARCHAR(255),
    extra_file               VARCHAR(255),
    achievement_file         VARCHAR(255),
    status                   VARCHAR(20)   DEFAULT 'pending',
    created_at               TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
);

-- ===== CLASSES TABLE =====
CREATE TABLE IF NOT EXISTS classes (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    class_name   VARCHAR(20)  NOT NULL UNIQUE,
    total_seats  INT          NOT NULL DEFAULT 30,
    filled_seats INT          NOT NULL DEFAULT 0
);

-- ===== SEED CLASS DATA (adjust total_seats as needed) =====
INSERT IGNORE INTO classes (class_name, total_seats) VALUES
('Nursery', 30), ('LKG', 30), ('UKG', 30),
('CL-I',   40), ('CL-II',   40), ('CL-III',  40),
('CL-IV',  40), ('CL-V',    40), ('CL-VI',   40),
('CL-VII', 40), ('CL-VIII', 40), ('CL-IX',   40),
('CL-X',   40), ('CL-XI',   35), ('CL-XII',  35);

-- Add email column if not exists (run this if table already created)
ALTER TABLE students ADD COLUMN IF NOT EXISTS email VARCHAR(200);
