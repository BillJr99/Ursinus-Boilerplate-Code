# code-viz runner "java" (runners/java/Dockerfile).
# Full manual: the header of code-viz (`code-viz readme`, or README.md), sections 2 Architecture (Runners), 7 Kinds of visualization, 15 Where things run and safety.
# Eclipse Temurin JDK 21.0.13+9 (javac, java, and the JDI debugger interface for tracers/JdiTrace.java), for Java examples: frames and objects stepped line by line, or output only.
#
# How it is used: code-viz builds this image as code-viz-java:<hash of this file> the first time an
# example needs it (docker build --network host: downloads time out on minipc's default bridge),
# runs examples in throwaway containers with --network none, --cpus 1, --memory 1g, --pids-limit 256,
# mounting the tracers read-only at /viz/tracers and the job folder at /work (tracers/driver.py and
# tracers/langrun.py), and removes the image afterwards unless --keep-images.
# Change the pinned versions here; the new hash makes code-viz rebuild. python3 is only the driver.
FROM eclipse-temurin:21.0.13_9-jdk-noble
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends python3 && rm -rf /var/lib/apt/lists/*
WORKDIR /work
