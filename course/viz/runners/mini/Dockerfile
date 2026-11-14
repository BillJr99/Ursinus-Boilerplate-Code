# code-viz runner. Built and run by code-viz in a throwaway container: no network at run time
# (agents: Ollama only), capped CPU, memory and processes, removed after the build.
# The CS374 Mini (mininote) interpreter is built from the course repo's files/examples/mininote at run time.
FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends flex bison gcc libc6-dev make libfl-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /work
