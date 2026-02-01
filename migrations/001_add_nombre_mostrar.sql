-- Migración: agregar campo nombre_mostrar a tabla users
-- Ejecutar en MariaDB/MySQL:
--   mysql -u usuario -p kpi_dashboard < migrations/001_add_nombre_mostrar.sql

ALTER TABLE users ADD COLUMN nombre_mostrar VARCHAR(120) NULL AFTER nombre;

-- Verificar:
-- DESCRIBE users;
