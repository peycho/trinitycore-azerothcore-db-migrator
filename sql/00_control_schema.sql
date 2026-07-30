CREATE DATABASE IF NOT EXISTS `{{CONTROL_SCHEMA}}`
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `{{CONTROL_SCHEMA}}`.`migration_run` (
  `run_id` char(36) NOT NULL,
  `config_hash` char(64) NOT NULL,
  `source_auth_fingerprint` char(64) DEFAULT NULL,
  `source_characters_fingerprint` char(64) DEFAULT NULL,
  `target_auth_fingerprint` char(64) DEFAULT NULL,
  `target_characters_fingerprint` char(64) DEFAULT NULL,
  `trinitycore_revision` varchar(40) NOT NULL,
  `azerothcore_revision` varchar(40) NOT NULL,
  `started_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `status` enum('RUNNING','READY','FAILED','COMPLETE') NOT NULL DEFAULT 'RUNNING',
  PRIMARY KEY (`run_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `{{CONTROL_SCHEMA}}`.`phase_checkpoint` (
  `run_id` char(36) NOT NULL,
  `phase_name` varchar(64) NOT NULL,
  `status` enum('RUNNING','COMPLETE','FAILED') NOT NULL,
  `started_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `finished_at` timestamp NULL DEFAULT NULL,
  `detail` text,
  PRIMARY KEY (`run_id`,`phase_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `{{CONTROL_SCHEMA}}`.`chunk_checkpoint` (
  `run_id` char(36) NOT NULL,
  `database_kind` enum('auth','characters') NOT NULL,
  `source_table` varchar(64) NOT NULL,
  `target_table` varchar(64) NOT NULL,
  `chunk_start` bigint NOT NULL,
  `chunk_end` bigint NOT NULL,
  `script_hash` char(64) NOT NULL,
  `source_rows` bigint unsigned NOT NULL,
  `target_rows` bigint unsigned NOT NULL,
  `status` enum('COMPLETE','FAILED') NOT NULL,
  `finished_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`run_id`,`database_kind`,`target_table`,`chunk_start`,`chunk_end`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `{{CONTROL_SCHEMA}}`.`source_table_snapshot` (
  `run_id` char(36) NOT NULL,
  `database_kind` enum('auth','characters') NOT NULL,
  `table_name` varchar(64) NOT NULL,
  `row_count` bigint unsigned NOT NULL,
  `captured_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`run_id`,`database_kind`,`table_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `{{CONTROL_SCHEMA}}`.`migration_reject` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `run_id` char(36) NOT NULL,
  `database_kind` enum('auth','characters') NOT NULL,
  `source_table` varchar(64) NOT NULL,
  `source_key` varchar(255) NOT NULL,
  `reason_code` varchar(64) NOT NULL,
  `reason_detail` text NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_run` (`run_id`,`database_kind`,`source_table`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `{{CONTROL_SCHEMA}}`.`validation_result` (
  `run_id` char(36) NOT NULL,
  `check_name` varchar(128) NOT NULL,
  `severity` enum('INFO','WARNING','ERROR') NOT NULL,
  `observed_value` varchar(255) NOT NULL,
  `expected_value` varchar(255) NOT NULL,
  `passed` tinyint(1) NOT NULL,
  `detail` text,
  `checked_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`run_id`,`check_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `{{CONTROL_SCHEMA}}`.`cleanup_orphan_character` (
  `run_id` char(36) NOT NULL,
  `guid` int unsigned NOT NULL,
  `account_id` int unsigned NOT NULL,
  `character_name` varchar(12) NOT NULL,
  `captured_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`run_id`,`guid`),
  KEY `idx_cleanup_orphan_account` (`run_id`,`account_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `{{CONTROL_SCHEMA}}`.`cleanup_table_summary` (
  `run_id` char(36) NOT NULL,
  `database_kind` enum('auth','characters') NOT NULL,
  `table_name` varchar(64) NOT NULL,
  `before_rows` bigint unsigned NOT NULL,
  `after_rows` bigint unsigned DEFAULT NULL,
  `removed_rows` bigint unsigned DEFAULT NULL,
  `detail` varchar(255) NOT NULL DEFAULT 'TARGET_SANITIZATION',
  `captured_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`run_id`,`database_kind`,`table_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
