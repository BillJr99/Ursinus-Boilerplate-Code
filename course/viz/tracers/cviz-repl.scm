;; code-viz: run a Scheme file the way the REPL would, printing the value of each top-level form
;; Full manual: the header of code-viz (`code-viz readme`, or README.md), sections 7 Kinds of visualization (env, Scheme), 14 Trace format.
;; (unless it is unspecified), so examples that end with a bare expression show their result.
;; Usage: guile --no-auto-compile -s cviz-repl.scm PROGRAM.scm
;; Pipeline: tracers/driver.py runs this in the scheme runner for every viz=env Scheme example and
;; stores what it prints as the trace's reference_stdout; when that differs from schemetrace.py's own
;; output the trace is marked "approximate" and this output is the one build --check compares.
;; Limits: a program that reads input or never ends is stopped by the job timeout.
(define (cviz-run file)
  (call-with-input-file file
    (lambda (port)
      (let loop ((form (read port)))
        (unless (eof-object? form)
          (call-with-values (lambda () (eval form (interaction-environment)))
            (lambda vals
              (for-each (lambda (v) (unless (unspecified? v) (write v) (newline))) vals)))
          (loop (read port)))))))
(cviz-run (cadr (command-line)))
