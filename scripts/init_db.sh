#!/bin/bash
# Database initialization script for REXM AI

echo "Initializing REXM AI Database..."

# Create database
psql -U postgres -c "CREATE DATABASE rexm_ai;"

# Create user
psql -U postgres -c "CREATE USER rexm_user WITH PASSWORD 'secure_password_here';"

# Grant privileges
psql -U postgres -c "ALTER ROLE rexm_user SET client_encoding TO 'utf8';"
psql -U postgres -c "ALTER ROLE rexm_user SET default_transaction_isolation TO 'read committed';"
psql -U postgres -c "ALTER ROLE rexm_user SET default_transaction_deferrable TO on;"
psql -U postgres -c "ALTER ROLE rexm_user SET default_transaction_read_only TO off;"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE rexm_ai TO rexm_user;"

echo "Database initialized successfully!"
