# code-viz runner. Built and run by code-viz in a throwaway container: no network at run time
# (agents: Ollama only), capped CPU, memory and processes, removed after the build.
FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends nodejs npm && rm -rf /var/lib/apt/lists/* \
 && npm install -g promptfoo@0.96.2 && pip install --no-cache-dir requests==2.32.3 httpx==0.27.2 numpy==2.1.3 ollama==0.4.4
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
