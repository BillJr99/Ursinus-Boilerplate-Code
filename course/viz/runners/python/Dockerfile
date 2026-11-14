# code-viz runner. Built and run by code-viz in a throwaway container: no network at run time
# (agents: Ollama only), capped CPU, memory and processes, removed after the build.
FROM python:3.12-slim
RUN pip install --no-cache-dir numpy==2.1.3 pandas==2.2.3 scikit-learn==1.5.2 matplotlib==3.9.2 requests==2.32.3
ENV MPLBACKEND=Agg PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
