FROM apache/airflow:3.1.3-python3.11

USER root
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# /opt is root-owned, so the venv directory has to be created and handed to
# the airflow user before dropping privileges. Building it as root instead
# would leave a venv the airflow user cannot write to.
RUN mkdir -p /opt/dbt_venv && chown airflow: /opt/dbt_venv

USER airflow

# dbt lives in its own virtualenv, not Airflow's.
#
# The two projects pin incompatible versions of shared dependencies -- most
# visibly click, which Airflow holds below the version dbt-core requires.
# Installing both into one interpreter produces an environment that imports
# but misbehaves. Isolating dbt and calling its binary from a BashOperator is
# the standard fix, and it means either tool can be upgraded on its own.
RUN python -m venv /opt/dbt_venv \
    && /opt/dbt_venv/bin/pip install --no-cache-dir "dbt-postgres==1.11.0" \
    && /opt/dbt_venv/bin/dbt --version

# psycopg is for the loader task, which runs in Airflow's own interpreter.
RUN pip install --no-cache-dir "psycopg[binary]==3.3.6" "requests==2.32.5"
