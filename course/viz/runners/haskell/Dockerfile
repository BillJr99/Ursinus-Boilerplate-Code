# code-viz runner. Built and run by code-viz in a throwaway container: no network at run time
# (agents: Ollama only), capped CPU, memory and processes, removed after the build.
FROM python:3.12-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends ghc && rm -rf /var/lib/apt/lists/*
WORKDIR /work
