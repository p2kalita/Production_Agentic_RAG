ARG AIRFLOW_VERSION=3.0.3
FROM apache/airflow:${AIRFLOW_VERSION}

# Re-declare after FROM so it is usable in RUN steps.
ARG AIRFLOW_VERSION

# The base image runs as the `airflow` user; packages install into its user site.
USER airflow

# 1) CPU-only PyTorch (docling dependency). Installed alone from the PyTorch CPU
#    index so no CUDA libraries are pulled and no other package comes from that index.
RUN pip install --no-cache-dir torch torchvision \
        --index-url https://download.pytorch.org/whl/cpu

# 2) DAG dependencies. Pinning apache-airflow to the installed version in the same
#    command keeps pip from changing Airflow or its own dependencies (e.g. SQLAlchemy 1.4).
COPY requirements-airflow.txt /tmp/requirements-airflow.txt
RUN pip install --no-cache-dir \
        "apache-airflow==${AIRFLOW_VERSION}" \
        -r /tmp/requirements-airflow.txt
